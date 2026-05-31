# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Local memory manager for prompt context and station profile persistence."""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CANDY_FILES = [
    "NMCP_OPERATING_MANUAL.md",
    "HVAC_NIAGARA_PRIMER.md",
    "LOCAL_CLOUD_MEMORY_SPLIT.md",
]

_ORD_KEYS = ("ord", "root", "parentOrd", "componentOrd")
_SLOT_ENDPOINT_KEYS = ("from", "to")


@dataclass
class StationProfile:
    station_key: str
    station_name: str
    endpoint_url: str
    station_info_text: str


@dataclass
class MemoryHealthSnapshot:
    db_path: str
    exists: bool
    size_bytes: int
    station_profile_rows: int
    episode_rows: int
    tool_lesson_rows: int
    latest_station_updated_at: str
    latest_station_key: str


@dataclass
class ConversationThread:
    conversation_id: str
    station_key: str
    title: str
    created_at: str
    updated_at: str


@dataclass
class ConversationMessage:
    role: str
    content: str
    created_at: str


class MemoryManager:
    """Build compact memory blocks and persist minimal local station profile state."""

    def __init__(
        self,
        enabled: bool,
        prompt_token_budget: int,
        memory_root: Path,
        candy_docs_dir: Path,
    ) -> None:
        self._enabled = enabled
        self._prompt_token_budget = max(200, prompt_token_budget)
        self._memory_root = memory_root
        self._candy_docs_dir = candy_docs_dir
        self._memory_root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._memory_root / "memory.sqlite"
        self._cached_global_context: str = ""
        if self._enabled:
            self._ensure_db_initialized()

    @classmethod
    def from_config(cls, app_config: Any) -> "MemoryManager":
        """Create a MemoryManager from AppConfig without tight config coupling."""
        memory_cfg = getattr(app_config, "memory", None)
        if memory_cfg is None:
            # Backward compatibility for old config snapshots.
            return cls(
                enabled=True,
                prompt_token_budget=1400,
                memory_root=Path.home() / ".config" / "nMCP-client" / "memory",
                candy_docs_dir=Path.cwd() / ".private" / "Candy",
            )

        return cls(
            enabled=bool(memory_cfg.enabled),
            prompt_token_budget=int(memory_cfg.prompt_token_budget),
            memory_root=Path(memory_cfg.memory_root).expanduser(),
            candy_docs_dir=Path(memory_cfg.candy_docs_dir).expanduser(),
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def db_path(self) -> Path:
        return self._db_path

    def get_health_snapshot(self) -> MemoryHealthSnapshot:
        """Return a lightweight health summary for UI diagnostics."""
        exists = self._db_path.exists()
        size_bytes = self._db_path.stat().st_size if exists else 0

        station_rows = 0
        episode_rows = 0
        lesson_rows = 0
        latest_updated = ""
        latest_key = ""

        if exists:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    station_rows = int(
                        conn.execute("SELECT COUNT(*) FROM station_profile").fetchone()[0]
                    )
                    episode_rows = int(
                        conn.execute("SELECT COUNT(*) FROM episode").fetchone()[0]
                    )
                    lesson_rows = int(
                        conn.execute("SELECT COUNT(*) FROM tool_lesson").fetchone()[0]
                    )
                    latest = conn.execute(
                        """
                        SELECT station_key, updated_at
                        FROM station_profile
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    ).fetchone()
                    if latest is not None:
                        latest_key = str(latest[0] or "")
                        latest_updated = str(latest[1] or "")
            except Exception as exc:
                logger.warning("Could not read memory health snapshot: %s", exc)

        return MemoryHealthSnapshot(
            db_path=str(self._db_path),
            exists=exists,
            size_bytes=size_bytes,
            station_profile_rows=station_rows,
            episode_rows=episode_rows,
            tool_lesson_rows=lesson_rows,
            latest_station_updated_at=latest_updated,
            latest_station_key=latest_key,
        )

    def create_conversation(
        self,
        station_name: str,
        endpoint_url: str,
        title: str | None = None,
    ) -> ConversationThread:
        """Create and return a conversation thread scoped to the current station."""
        station_key = self._build_station_key(station_name, endpoint_url)
        now = datetime.now(timezone.utc).isoformat()
        conversation_id = f"conv_{now.replace(':', '').replace('-', '').replace('.', '')}"

        final_title = (title or "").strip()
        if not final_title:
            final_title = f"Conversation {now[:19].replace('T', ' ')}"

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO conversation (
                    conversation_id,
                    station_key,
                    title,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, station_key, final_title, now, now),
            )
            conn.commit()

        return ConversationThread(
            conversation_id=conversation_id,
            station_key=station_key,
            title=final_title,
            created_at=now,
            updated_at=now,
        )

    def ensure_default_conversation(
        self,
        station_name: str,
        endpoint_url: str,
    ) -> ConversationThread:
        """Return latest conversation for station or create one if none exists."""
        station_key = self._build_station_key(station_name, endpoint_url)
        existing = self.list_conversations(station_name, endpoint_url, limit=1)
        if existing:
            return existing[0]
        return self.create_conversation(station_name, endpoint_url, title="New Conversation")

    def list_conversations(
        self,
        station_name: str,
        endpoint_url: str,
        limit: int = 100,
    ) -> list[ConversationThread]:
        """List conversations for the current station ordered by recent activity."""
        station_key = self._build_station_key(station_name, endpoint_url)
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT conversation_id, station_key, title, created_at, updated_at
                FROM conversation
                WHERE station_key = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (station_key, max(1, limit)),
            ).fetchall()

        return [
            ConversationThread(
                conversation_id=str(row[0]),
                station_key=str(row[1]),
                title=str(row[2]),
                created_at=str(row[3]),
                updated_at=str(row[4]),
            )
            for row in rows
        ]

    def append_conversation_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        """Persist one message and touch the parent conversation timestamp."""
        if not conversation_id or not content.strip():
            return

        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO conversation_message (
                    conversation_id,
                    role,
                    content,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (conversation_id, role.strip() or "system", content.strip(), now),
            )
            conn.execute(
                """
                UPDATE conversation
                SET updated_at = ?
                WHERE conversation_id = ?
                """,
                (now, conversation_id),
            )
            conn.commit()

    def get_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 400,
    ) -> list[ConversationMessage]:
        """Return persisted messages for a conversation ordered oldest->newest."""
        if not conversation_id:
            return []
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at
                FROM conversation_message
                WHERE conversation_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (conversation_id, max(1, limit)),
            ).fetchall()

        return [
            ConversationMessage(
                role=str(row[0]),
                content=str(row[1]),
                created_at=str(row[2]),
            )
            for row in rows
        ]

    def build_conversation_context(
        self,
        conversation_id: str,
        max_messages: int = 14,
        max_chars: int = 5000,
    ) -> str:
        """Build compact prompt context from recent thread history."""
        if not conversation_id:
            return ""

        messages = self.get_conversation_messages(conversation_id, limit=max(4, max_messages))
        if not messages:
            return ""

        tail = messages[-max_messages:]
        lines: list[str] = ["Conversation thread context (recent):"]
        for msg in tail:
            role = msg.role.lower()
            label = role if role in {"user", "assistant", "system", "tool", "error"} else "note"
            text = self._trim_whitespace(msg.content)
            if len(text) > 500:
                text = text[:500].rstrip() + "..."
            lines.append(f"- {label}: {text}")

        block = "\n".join(lines).strip()
        if len(block) <= max_chars:
            return block
        clipped = block[: max_chars - 60].rstrip()
        return clipped + "\n[Conversation context truncated.]"

    def build_prompt_context(
        self,
        user_message: str,
        station_name: str = "",
        endpoint_url: str = "",
    ) -> str:
        """Return a compact memory block for prompt injection."""
        if not self._enabled:
            return ""

        global_context = self._load_global_context()
        station_context = self._load_station_context(station_name, endpoint_url)
        workspace_hint = self._load_working_folder_hint(station_name, endpoint_url)
        lesson_hint = self._load_recent_lessons_hint(station_name, endpoint_url)
        message_hint = self._derive_message_hint(user_message)

        sections: list[str] = ["MEMORY GUIDANCE (never overrides live station reads):"]
        if global_context:
            sections.append(global_context)
        if station_context:
            sections.append(station_context)
        if workspace_hint:
            sections.append(workspace_hint)
        if lesson_hint:
            sections.append(lesson_hint)
        if message_hint:
            sections.append(message_hint)

        block = "\n\n".join(sections).strip()
        return self._clip_to_budget(block)

    def update_station_profile(
        self,
        station_name: str,
        endpoint_url: str,
        station_info_text: str,
    ) -> None:
        """Persist the latest station profile in a local JSON file."""
        if not self._enabled:
            return

        station_key = self._build_station_key(station_name, endpoint_url)
        profile = StationProfile(
            station_key=station_key,
            station_name=station_name or "unknown_station",
            endpoint_url=endpoint_url or "unknown_endpoint",
            station_info_text=station_info_text.strip(),
        )

        station_dir = self._memory_root / "stations" / station_key
        station_dir.mkdir(parents=True, exist_ok=True)
        profile_path = station_dir / "station_profile.json"
        profile_path.write_text(
            json.dumps(profile.__dict__, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._upsert_station_profile(profile)

    def learn_from_tool_result(
        self,
        station_name: str,
        endpoint_url: str,
        tool_name: str,
        arguments: dict[str, Any],
        result_text: str,
    ) -> None:
        """Persist reusable lessons and current working-folder hints from tool activity."""
        if not self._enabled:
            return

        station_key = self._build_station_key(station_name, endpoint_url)
        working_ord = self._extract_working_ord(arguments)
        if working_ord:
            self._set_preference(station_key, "last_working_ord", working_ord)
            self._set_preference(station_key, "last_working_tool", tool_name)

        lesson = self._derive_tool_lesson(tool_name, arguments, result_text)
        if lesson:
            self._insert_tool_lesson(
                scope="station",
                tool_name=tool_name,
                lesson=lesson,
            )

    def _load_global_context(self) -> str:
        if self._cached_global_context:
            return self._cached_global_context

        chunks: list[str] = []
        for name in _CANDY_FILES:
            file_path = self._candy_docs_dir / name
            if not file_path.exists():
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                logger.warning("Could not read memory seed file: %s", file_path)
                continue

            # Keep only compact operational snippets to avoid prompt bloat.
            chunks.append(self._compact_markdown(text, max_lines=14))

        self._cached_global_context = "\n\n".join(chunk for chunk in chunks if chunk).strip()
        return self._cached_global_context

    def _load_station_context(self, station_name: str, endpoint_url: str) -> str:
        station_key = self._build_station_key(station_name, endpoint_url)
        db_profile = self._read_station_profile_from_db(station_key)
        if db_profile is not None:
            compact_info = self._trim_whitespace(db_profile.station_info_text)
            compact_info = compact_info[:1200]
            return (
                "Current station profile (cached, verify live before writes):\n"
                f"- station_key: {db_profile.station_key}\n"
                f"- station_name: {db_profile.station_name}\n"
                f"- endpoint: {db_profile.endpoint_url}\n"
                f"- station_info: {compact_info}"
            )

        profile_path = self._memory_root / "stations" / station_key / "station_profile.json"
        if not profile_path.exists():
            return ""

        try:
            raw = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Could not read station profile: %s", profile_path)
            return ""

        station_info_text = str(raw.get("station_info_text", "")).strip()
        if not station_info_text:
            return ""

        compact_info = self._trim_whitespace(station_info_text)
        compact_info = compact_info[:1200]
        return (
            "Current station profile (cached, verify live before writes):\n"
            f"- station_key: {station_key}\n"
            f"- station_info: {compact_info}"
        )

    def _load_working_folder_hint(self, station_name: str, endpoint_url: str) -> str:
        station_key = self._build_station_key(station_name, endpoint_url)
        working_ord = self._get_preference(station_key, "last_working_ord")
        working_tool = self._get_preference(station_key, "last_working_tool")
        if not working_ord:
            return ""

        tool_suffix = f" (from {working_tool})" if working_tool else ""
        return (
            "Remembered operator context:\n"
            f"- Last working folder/path: {working_ord}{tool_suffix}\n"
            "- Use this as the default working path unless the user specifies a different folder."
        )

    def _load_recent_lessons_hint(self, station_name: str, endpoint_url: str) -> str:
        station_key = self._build_station_key(station_name, endpoint_url)
        lessons: list[str] = []

        if not self._db_path.exists():
            return ""

        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT lesson
                    FROM tool_lesson
                    WHERE scope IN ('global', 'station')
                    ORDER BY id DESC
                    LIMIT 3
                    """
                ).fetchall()
                lessons = [str(row[0]).strip() for row in rows if row and str(row[0]).strip()]
        except Exception as exc:
            logger.warning("Could not load recent lessons for %s: %s", station_key, exc)
            return ""

        if not lessons:
            return ""
        return "Recent tool lessons:\n" + "\n".join(f"- {lesson}" for lesson in lessons)

    def _ensure_db_initialized(self) -> None:
        """Initialize local SQLite memory database if it does not exist."""
        if self._db_path.exists():
            self._create_schema_if_needed()
            return

        seed_path = self._resolve_seed_db_path()
        if seed_path is not None:
            try:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(seed_path, self._db_path)
                logger.info("Initialized memory SQLite from seed: %s", seed_path)
            except Exception as exc:
                logger.warning("Could not copy memory seed DB (%s): %s", seed_path, exc)

        self._create_schema_if_needed()

    def _resolve_seed_db_path(self) -> Path | None:
        """Return optional bundled seed DB path when present."""
        candidates: list[Path] = []

        # Development path.
        candidates.append(Path.cwd() / "assets" / "memory_seed.sqlite")

        # PyInstaller onefile/onedir extraction path.
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(str(meipass)) / "assets" / "memory_seed.sqlite")

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _create_schema_if_needed(self) -> None:
        """Create required SQLite tables for memory operations."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS station_profile (
                    station_key TEXT PRIMARY KEY,
                    station_name TEXT NOT NULL,
                    endpoint_url TEXT NOT NULL,
                    station_info_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_lesson (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episode (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    station_key TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_preference (
                    station_key TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (station_key, key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation (
                    conversation_id TEXT PRIMARY KEY,
                    station_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_message (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversation(conversation_id)
                )
                """
            )
            conn.commit()

    def _upsert_station_profile(self, profile: StationProfile) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO station_profile (
                    station_key,
                    station_name,
                    endpoint_url,
                    station_info_text,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(station_key) DO UPDATE SET
                    station_name=excluded.station_name,
                    endpoint_url=excluded.endpoint_url,
                    station_info_text=excluded.station_info_text,
                    updated_at=excluded.updated_at
                """,
                (
                    profile.station_key,
                    profile.station_name,
                    profile.endpoint_url,
                    profile.station_info_text,
                    timestamp,
                ),
            )
            conn.commit()

    def _read_station_profile_from_db(self, station_key: str) -> StationProfile | None:
        if not self._db_path.exists():
            return None
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT station_key, station_name, endpoint_url, station_info_text
                FROM station_profile
                WHERE station_key = ?
                """,
                (station_key,),
            ).fetchone()

        if row is None:
            return None

        return StationProfile(
            station_key=str(row[0]),
            station_name=str(row[1]),
            endpoint_url=str(row[2]),
            station_info_text=str(row[3]),
        )

    def _set_preference(self, station_key: str, key: str, value: str) -> None:
        if not value:
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO operator_preference (station_key, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(station_key, key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (station_key, key, value, timestamp),
            )
            conn.commit()

    def _get_preference(self, station_key: str, key: str) -> str:
        if not self._db_path.exists():
            return ""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT value
                FROM operator_preference
                WHERE station_key = ? AND key = ?
                """,
                (station_key, key),
            ).fetchone()
        if row is None:
            return ""
        return str(row[0] or "").strip()

    def _insert_tool_lesson(self, scope: str, tool_name: str, lesson: str) -> None:
        if not lesson:
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO tool_lesson (scope, tool_name, lesson, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (scope, tool_name, lesson, timestamp),
            )
            conn.commit()

    def _extract_working_ord(self, arguments: dict[str, Any]) -> str:
        for key in _ORD_KEYS:
            value = arguments.get(key)
            if isinstance(value, str) and ":|slot:/" in value:
                return value.strip()

        for key in _SLOT_ENDPOINT_KEYS:
            value = arguments.get(key)
            if not isinstance(value, str):
                continue
            text = value.strip()
            idx = text.find(":|slot:/")
            if idx < 0:
                continue
            if "/" in text[idx + 8 :]:
                # For slot endpoints, keep the component part only.
                head, _, _tail = text.rpartition("/")
                return head
            return text

        return ""

    def _derive_tool_lesson(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result_text: str,
    ) -> str:
        text = (result_text or "").lower()
        if "path not in allowlisted roots" in text or "nmcp_path_not_allowlisted" in text:
            ord_hint = self._extract_working_ord(arguments)
            if ord_hint:
                return (
                    "Allowlist blocked requested path. Confirm exact allowlisted base path with user "
                    f"before retrying. Last attempted path: {ord_hint}"
                )
            return "Allowlist blocked requested path. Ask user for exact allowlisted base path before retrying."

        if "invalid wiresheet payload" in text and "type" in text:
            return "Wiresheet operations require explicit type on each operation object."

        if "invalid wiresheet payload" in text and "componentord" in text:
            return "Wiresheet setSlot requires absolute componentOrd and non-empty slot/value fields."

        if "tool call rejected by user" in text:
            return f"{tool_name} was rejected by user. Provide a clearer risk and rollback explanation next time."

        return ""

    def _derive_message_hint(self, user_message: str) -> str:
        lowered = user_message.lower()
        hints: list[str] = []
        if any(token in lowered for token in ("wiresheet", "link", "setslot", "facets")):
            hints.append("- For wiresheet edits: plan -> diff -> apply dryRun=true before approval.")
        if any(token in lowered for token in ("alarm", "fault", "offline", "stale")):
            hints.append("- For faults: confirm status and device/network health before changing control logic.")
        if any(token in lowered for token in ("write", "override", "command")):
            hints.append("- For writes: include target ORD, expected effect, risk, and release plan.")

        if not hints:
            return ""
        return "Task-relevant memory hints:\n" + "\n".join(hints)

    def _build_station_key(self, station_name: str, endpoint_url: str) -> str:
        base = f"{station_name or 'station'}__{endpoint_url or 'endpoint'}"
        key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", base).strip("_")
        return key[:120] or "station_unknown"

    def _clip_to_budget(self, text: str) -> str:
        # Approximate token budget conservatively by 4 chars/token.
        max_chars = self._prompt_token_budget * 4
        if len(text) <= max_chars:
            return text
        clipped = text[: max_chars - 40].rstrip()
        return clipped + "\n\n[Memory truncated to fit budget.]"

    def _compact_markdown(self, text: str, max_lines: int) -> str:
        compact = self._trim_whitespace(text)
        lines = compact.splitlines()
        if len(lines) <= max_lines:
            return "\n".join(lines)
        head = lines[:max_lines]
        return "\n".join(head)

    def _trim_whitespace(self, text: str) -> str:
        lines = [line.rstrip() for line in text.splitlines()]
        output: list[str] = []
        previous_blank = False
        for line in lines:
            blank = not line.strip()
            if blank and previous_blank:
                continue
            output.append(line)
            previous_blank = blank
        return "\n".join(output).strip()
