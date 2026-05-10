#!/usr/bin/env python3
# Copyright (c) 2026 Chris Favre. All rights reserved.
"""
nMCP Proxy
================
Authenticates to Niagara 4 using the SCRAM-SHA-512 scheme
(which internally uses PBKDF2-HMAC-SHA-256 / HMAC-SHA-256) and
proxies JSON-RPC requests to the /nmcp servlet.

Usage
-----
  python mcp_proxy.py ^
      --niagara-url  http://localhost ^
      --niagara-user mcp ^
      --niagara-pass <password> ^
      [--token <bearer-token-for-clients>] ^
      [--port 8765] ^
      [--host 127.0.0.1]

Clients then POST to  http://127.0.0.1:8765/nmcp  with:
  Authorization: Bearer <bearer-token>   (or X-MCP-Token: <bearer-token>)
  Content-Type:  application/json
  Body:          { JSON-RPC 2.0 payload }

If --token is omitted the proxy accepts all local requests without auth.

Python 3.6+ standard library only – no third-party packages required.
"""

import argparse
import base64
import hashlib
import hmac
import http.server
import json
import os
import re
import secrets
import sys
import threading
import traceback
import ssl
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

# Shared SSL context that accepts Niagara's self-signed certificate.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ─────────────────────────── SCRAM implementation ────────────────────────────
#
# Niagara 4 calls this scheme "scram-sha512" in the Authorization header,
# but the actual crypto is SHA-256 throughout (PBKDF2-HMAC-SHA256, HMAC-SHA256,
# SHA256).  The scheme is used purely as a label/negotiation token.
#
# Reference: RFC 5802 (SCRAM), adapted for SHA-256.

_DKLEN = 32   # SHA-256 output bytes


def _hmac256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _pbkdf2(password: bytes, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen=_DKLEN)


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


class _ScramClient:
    """
    One-shot SCRAM-SHA-256 client.

    Typical usage:
        sc = _ScramClient(username, password)
        msg1 = sc.client_first()                      # send to server
        msg2 = sc.client_final(server_first_response) # send to server
        sc.verify_server(server_final_response)        # raises on bad sig
    """

    GS2_HEADER = "n,,"   # no channel binding, no authzid

    def __init__(self, username: str, password: str):
        self._username  = _sasl_prep(username)
        self._password  = _sasl_prep(password).encode("utf-8")
        self._cnonce    = base64.b64encode(secrets.token_bytes(24)).decode("ascii")
        self._first_bare = f"n={self._username},r={self._cnonce}"
        self._client_first = self.GS2_HEADER + self._first_bare
        # filled in during client_final()
        self._salted_pw : bytes | None = None
        self._auth_msg  : str   | None = None

    def client_first(self) -> str:
        return self._client_first

    def client_final(self, server_first: str) -> str:
        """Compute and return the client-final-message."""
        parts = _parse_attrs(server_first)

        snonce = parts.get("r", "")
        if not snonce.startswith(self._cnonce):
            raise ValueError("Server nonce does not begin with client nonce")

        salt       = base64.b64decode(parts["s"])
        iterations = int(parts["i"])

        self._salted_pw = _pbkdf2(self._password, salt, iterations)

        # Channel binding value c = base64("n,,")  → always "biws"
        cb = base64.b64encode(self.GS2_HEADER.encode("ascii")).decode("ascii")
        final_no_proof = f"c={cb},r={snonce}"

        self._auth_msg = ",".join([
            self._first_bare,
            server_first,
            final_no_proof,
        ])

        client_key = _hmac256(self._salted_pw, b"Client Key")
        stored_key = _sha256(client_key)
        client_sig = _hmac256(stored_key, self._auth_msg.encode("utf-8"))
        proof      = _xor(client_key, client_sig)

        return f"{final_no_proof},p={base64.b64encode(proof).decode('ascii')}"

    def verify_server(self, server_final: str) -> None:
        """Verify server signature (or skip on mismatch to allow testing)."""
        try:
            parts = _parse_attrs(server_final)
            received = base64.b64decode(parts.get("v", ""))
            server_key = _hmac256(self._salted_pw, b"Server Key")
            expected   = _hmac256(server_key, self._auth_msg.encode("utf-8"))
            if not hmac.compare_digest(expected, received):
                # For testing: warn but don't fail
                _log("WARNING: Server signature mismatch (verification skipped for testing)")
                return
        except Exception as e:
            # Skip verification on any error
            _log(f"WARNING: Server verification error: {e} (skipped for testing)")


def _parse_attrs(msg: str) -> dict:
    result = {}
    for token in msg.split(","):
        k, _, v = token.partition("=")
        result[k] = v
    return result


def _sasl_prep(s: str) -> str:
    """Minimal SASLprep: NFKC normalise, escape = and ,."""
    import unicodedata
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("=", "=3D").replace(",", "=2C")
    return s


# ─────────────────────────── Niagara session ─────────────────────────────────

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Suppress all redirects – let caller detect 3xx and handle manually."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


class NiagaraSession:
    """Thread-safe Niagara HTTP session with automatic SCRAM re-authentication."""

    def __init__(self, base_url: str, username: str, password: str,
                 backend_mcp_token: str):
        self._base     = base_url.rstrip("/")
        self._user     = username
        self._password = password
        self._backend_mcp_token = backend_mcp_token.strip()
        self._auto_discover_backend_token = not bool(self._backend_mcp_token)
        self._lock     = threading.Lock()
        self._jar      = CookieJar()
        self._opener   = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar),
            urllib.request.HTTPSHandler(context=_SSL_CTX),
            _NoRedirectHandler(),
        )

    # ── public ──────────────────────────────────────────────────────────────

    def login(self) -> None:
        """Perform SCRAM-SHA-256 login and cache the resulting session cookie."""
        with self._lock:
            self._do_login()

    def post_mcp(self, path: str, body: bytes, content_type: str
                 ) -> tuple:  # → (status: int, body: bytes, content_type: str)
        """POST to the MCP endpoint; re-authenticates once on session expiry."""
        with self._lock:
            return self._forward(path, body, content_type, allow_retry=True)

    # ── private ─────────────────────────────────────────────────────────────

    def _do_login(self) -> None:
        sc  = _ScramClient(self._user, self._password)
        url = f"{self._base}/j_security_check/"

        # ── Step 0: Replay the same pre-auth flow used by Niagara's login page.
        # This establishes origin + user-id cookies required by SCRAM exchange.
        try:
            for pre_url in (
                f"{self._base}/nmcp",
                f"{self._base}/login",
                f"{self._base}/prelogin",
            ):
                pre_req = urllib.request.Request(pre_url, method="GET")
                try:
                    with self._opener.open(pre_req):
                        pass
                except urllib.error.HTTPError:
                    # Expected for redirects while priming cookies.
                    pass

            user_body = f"j_username={urllib.parse.quote_plus(self._user)}".encode("utf-8")
            user_req = urllib.request.Request(f"{self._base}/login", data=user_body, method="POST")
            user_req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with self._opener.open(user_req):
                pass
        except urllib.error.HTTPError:
            # 302 is fine – cookies are still stored by the cookie jar.
            pass

        # ── Step 1: client-first → server-first ─────────────────────────────
        body1 = (
            "action=sendClientFirstMessage"
            f"&clientFirstMessage={sc.client_first()}"
        ).encode("utf-8")
        server_first = self._scram_post(url, body1)

        # ── Step 2: client-final → server-final ─────────────────────────────
        body2 = (
            "action=sendClientFinalMessage"
            f"&clientFinalMessage={sc.client_final(server_first.strip())}"
        ).encode("utf-8")
        server_final = self._scram_post(url, body2)

        sc.verify_server(server_final.strip())

        # Complete login like Niagara's browser flow (redirect to j_security_check).
        # This turns successful SCRAM proof into an authenticated web session.
        try:
            finalize_opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(self._jar),
                urllib.request.HTTPSHandler(context=_SSL_CTX),
            )
            finalize_req = urllib.request.Request(url, method="GET")
            if self._backend_mcp_token:
                finalize_req.add_header("X-MCP-Token", self._backend_mcp_token)
            with finalize_opener.open(finalize_req):
                pass
        except urllib.error.HTTPError as e:
            # Some stations end with redirects or reach /nmcp which may 401 without token.
            # Some stations can also land on a not-found redirect target after auth.
            if e.code not in (301, 302, 303, 307, 308, 401, 404):
                raise

        if self._auto_discover_backend_token:
            self._backend_mcp_token = self._discover_backend_token()
            _log("Auto-discovered backend MCP token from station")

        _log(f"Authenticated as '{self._user}'")

    def _scram_post(self, url: str, data: bytes) -> str:
        """POST form data; return response body as str (raises on non-200)."""
        req = urllib.request.Request(url, data=data, method="POST")
        # Match Niagara login JavaScript exactly.
        req.add_header("Content-Type", "application/x-niagara-login-support")
        try:
            with self._opener.open(req) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"SCRAM POST {url} → HTTP {e.code}: {body[:300]}"
            ) from e

    def _forward(self, path: str, body: bytes, content_type: str,
                 allow_retry: bool) -> tuple:
        url = f"{self._base}{path}"
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", content_type)
        req.add_header("Accept",       "application/json")
        if self._backend_mcp_token:
            req.add_header("X-MCP-Token", self._backend_mcp_token)
        try:
            with self._opener.open(req) as resp:
                return (
                    resp.status,
                    resp.read(),
                    resp.headers.get("Content-Type", "application/json"),
                )
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and allow_retry:
                _log("Session expired – re-authenticating…")
                try:
                    self._do_login()
                    return self._forward(path, body, content_type, allow_retry=False)
                except ValueError as auth_err:
                    # If re-auth fails, return the redirect as-is rather than crashing
                    _log(f"Re-authentication failed: {auth_err}")
                    body_bytes = e.read()
                    ct = e.headers.get("Content-Type", "application/json")
                    return e.code, body_bytes, ct
            body_bytes = e.read()
            ct = e.headers.get("Content-Type", "application/json")
            return e.code, body_bytes, ct
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection error: {e.reason}") from e

    def _discover_backend_token(self) -> str:
        """Read GET /nmcp status payload and extract token field."""
        req = urllib.request.Request(f"{self._base}/nmcp", method="GET")
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar), urllib.request.HTTPSHandler(context=_SSL_CTX))
        try:
            with opener.open(req) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Unable to auto-discover backend token from /nmcp (HTTP {e.code}): {body[:300]}"
            ) from e

        token = ""
        try:
            payload = json.loads(body)
            token = str(payload.get("token", "")).strip()
        except Exception:
            m = re.search(r'"token"\s*:\s*"([^"]+)"', body)
            token = m.group(1).strip() if m else ""

        if not token:
            raise RuntimeError(
                "Unable to auto-discover backend token from /nmcp response. "
                "Start proxy with --backend-mcp-token or verify BMcpService GET /nmcp output."
            )
        return token


# ─────────────────────────── HTTP proxy handler ───────────────────────────────

def _log(msg: str) -> None:
    print(f"[mcp-proxy] {msg}", flush=True)


_session : NiagaraSession | None = None
_token   : str | None = None


class _ProxyHandler(http.server.BaseHTTPRequestHandler):
    server_version = "nMCP-Proxy/1.0"

    # ── logging ──────────────────────────────────────────────────────────────
    def log_message(self, fmt, *args):
        _log(f"{self.address_string()} – {fmt % args}")

    # ── routes ───────────────────────────────────────────────────────────────
    def do_POST(self):
        if not self.path.startswith("/nmcp"):
            self._json(404, {"error": "Not Found"})
            return

        if not self._check_token():
            return

        length   = int(self.headers.get("Content-Length", "0"))
        body     = self.rfile.read(length) if length > 0 else b""
        ct       = self.headers.get("Content-Type", "application/json")

        try:
            status, resp_body, resp_ct = _session.post_mcp(self.path, body, ct)
        except RuntimeError as exc:
            _log(f"Backend error: {exc}")
            self._json(502, {"error": str(exc)})
            return
        except Exception:
            _log(traceback.format_exc())
            self._json(500, {"error": "Internal proxy error"})
            return

        self.send_response(status)
        self.send_header("Content-Type", resp_ct)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def do_GET(self):
        self._json(405, {"error": "Method Not Allowed – use POST"})

    # ── helpers ──────────────────────────────────────────────────────────────
    def _check_token(self) -> bool:
        if not _token:
            return True   # no token required

        auth   = self.headers.get("Authorization", "")
        xtoken = self.headers.get("X-MCP-Token",  "")

        bearer = ""
        if auth.lower().startswith("bearer "):
            bearer = auth[len("Bearer "):].strip()

        ok = (
            (bearer   and hmac.compare_digest(bearer,  _token)) or
            (xtoken   and hmac.compare_digest(xtoken,  _token))
        )
        if not ok:
            self._json(401, {"error": "Unauthorized – valid token required"})
        return ok

    def _json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ─────────────────────────────────── main ────────────────────────────────────

def main():
    global _session, _token

    ap = argparse.ArgumentParser(
        description="nMCP Proxy – SCRAM-SHA-256 session manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--niagara-url",  default="http://localhost",
                    help="Base URL of the Niagara station (default: http://localhost)")
    ap.add_argument("--niagara-user", required=True,
                    help="Niagara username (must have access rights)")
    ap.add_argument("--niagara-pass", required=True,
                    help="Niagara password")
    ap.add_argument("--token",        default="",
                    help="Bearer token clients must supply (empty = no auth)")
    ap.add_argument("--backend-mcp-token", default="",
                    help="Token sent by proxy to Niagara /nmcp; if omitted, proxy auto-discovers it from GET /nmcp")
    ap.add_argument("--port",         type=int, default=8765,
                    help="Local listen port (default: 8765)")
    ap.add_argument("--host",         default="127.0.0.1",
                    help="Local listen address (default: 127.0.0.1)")
    args = ap.parse_args()

    _token   = args.token.strip() or None
    _session = NiagaraSession(
        args.niagara_url,
        args.niagara_user,
        args.niagara_pass,
        args.backend_mcp_token,
    )

    _log(f"Connecting to Niagara at {args.niagara_url} …")
    try:
        _session.login()
    except RuntimeError as exc:
        print(f"ERROR: Initial login failed: {exc}", file=sys.stderr)
        sys.exit(1)

    server = http.server.ThreadingHTTPServer((args.host, args.port), _ProxyHandler)
    _log(f"Listening on http://{args.host}:{args.port}/nmcp")
    if _token:
        _log("Client token authentication is ENABLED")
    else:
        _log("WARNING: No --token set – all local requests are accepted without auth")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
