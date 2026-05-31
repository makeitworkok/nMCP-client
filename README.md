# nMCP-client

Version: 0.0.1

Compatibility: Requires nMCP.jar v0.8.0+.

Lightweight desktop MCP client for [nMCP server](https://github.com/makeitworkok/nMCP) connections.

A PySide6 desktop application that connects to an MCP server, discovers available tools, and lets an LLM carry out BAS tasks (creating points, listing components, linking/wiring, etc.) with a human-approval gate for all write operations.

---

## Features

| Feature | Status |
|---|---|
| Streamable HTTP MCP transport | ✅ |
| SSE MCP transport (fallback) | ✅ |
| Tool discovery & schema viewer | ✅ |
| Chat / workbench interface | ✅ |
| Agentic loop (LLM ↔ MCP) | ✅ |
| Plan Mode (review before writes) | ✅ |
| Read-only tools execute immediately | ✅ |
| Write tools require explicit approval | ✅ |
| In-app About dialog | ✅ |
| In-app Quick Help (Quickstart/API keys) | ✅ |
| OpenAI (GPT-4o, …) | ✅ |
| Anthropic (Claude) | ⚠️ Not yet tested |
| xAI (Grok) | ⚠️ Not yet tested |
| OpenRouter | ⚠️ Not yet tested |
| Ollama (local) | ⚠️ Not yet tested |
| Rotating log file | ✅ |
| Persistent per-user config (outside `dist`) | ✅ |

---

## Project structure

```
nMCP-client/
├── main.py                  # entry point
├── config.py                # Pydantic AppConfig + JSON persistence
├── requirements.txt
├── pyproject.toml
├── .env.example
├── logs/                    # rotating log files (gitignored at runtime)
└── src/
    ├── async_runner.py      # asyncio event loop in a QThread
    ├── mcp_client.py        # MCP session (connect / list_tools / call_tool)
    ├── safety.py            # write-tool detection + approval explanations
    ├── agent.py             # agentic loop (LLM ↔ MCP ↔ approval signals)
    ├── llm/
    │   ├── base.py          # abstract BaseLLMProvider
    │   ├── openai_provider.py
    │   ├── anthropic_provider.py
    │   ├── xai_provider.py
    │   ├── openrouter_provider.py
    │   └── ollama_provider.py
    └── ui/
        ├── app.py           # MainWindow
        ├── connection_widget.py
        ├── tools_widget.py
        ├── chat_widget.py
        ├── approval_dialog.py
        ├── plan_review_dialog.py
        ├── help_dialog.py
        └── about_dialog.py
```

---

## Quick start

### 1. Clone & install

```bash
git clone https://github.com/makeitworkok/nMCP-client.git
cd nMCP-client

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure environment (optional)

```bash
cp .env.example .env
# Edit .env — add your API keys and MCP server URL
```

### 3. Run

```bash
python main.py
```

---

## Configuration

Settings are persisted to a per-user config file automatically when you click **Connect**:

- Windows: `%APPDATA%\\nMCP-client\\config.json`
- macOS: `~/Library/Application Support/nMCP-client/config.json`
- Linux: `$XDG_CONFIG_HOME/nMCP-client/config.json` (or `~/.config/nMCP-client/config.json`)

### Connection tab

| Field | Description |
|---|---|
| **URL** | Full MCP endpoint, e.g. `http://localhost:8000/mcp` |
| **Station** | Niagara station name (forwarded to tools as context) |
| **Username / Password** | HTTP Basic auth (used when no token is provided) |
| **Token** | Bearer token — overrides username/password |

### LLM Provider tab

| Field | Description |
|---|---|
| **Provider** | `openai` · `anthropic` · `xai` · `openrouter` · `ollama` |
| **Model** | Model name (e.g. `gpt-4o`, `claude-opus-4-5`, `grok-3`, `openai/gpt-4o-mini`, `llama3.1`) |
| **API Key** | Provider API key (auto-filled from env if `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, etc. are set) |
| **Base URL** | Optional override (defaults are set per provider) |

---

## Safety workflow

* **Read-only tools** (any tool whose name does _not_ match write patterns) execute immediately.
* **Plan Mode** (chat toggle) first generates a checklist + detailed plan preview for the request.
* In Plan Mode, **write actions are blocked** until you approve the plan for the current turn.
* **Write tools** — names starting with `create_`, `delete_`, `update_`, `set_`, `link_`, `wire_`, `rename_`, etc. — trigger an **Approval Dialog** before execution.
* The dialog shows: tool name · arguments (JSON) · plain-English explanation.
* Rejecting a write tool sends a "rejected by user" result back to the LLM so it can respond gracefully.
* All approved actions are logged to `logs/nmcp_client.log`.

---

## Help and About

Use the **Help** menu in the main window:

* **Quick Help** opens a tabbed guide with:
    * Quickstart steps
    * API key acquisition guidance for OpenAI, Anthropic, xAI, and OpenRouter
    * Troubleshooting tips for common connection/model/key issues
* **About nMCP Client** shows:
    * App name and version (read from `pyproject.toml`)
    * Author name
    * Repository link
    * Placeholder section for future update checks (no network calls yet)

---

## Agent Reliability

To keep the agent from relearning the same operational lessons, this repo now includes persistent guidance files:

* `AGENTS.md` - high-priority operating rules and error-handling guardrails.
* `docs/niagara-agent-playbook.md` - canonical payload templates, execution sequences, and fix maps.
* `docs/agent-lessons.md` - rolling incident log for newly discovered failures and corrections.

Recommended maintenance workflow:

1. Add each new recurring issue to `docs/agent-lessons.md`.
2. Promote broad rules to `AGENTS.md`.
3. Add reusable payload patterns to `docs/niagara-agent-playbook.md`.

---

## Adding a new LLM provider

1. Create `src/llm/my_provider.py` subclassing `BaseLLMProvider`.
2. Implement `reset_conversation`, `add_user_message`, `add_tool_results_batch`, and `get_response`.
3. Register the provider name in `src/ui/connection_widget.py` (`_PROVIDERS` list) and `src/ui/app.py` (`_create_llm_provider`).

---

## Requirements

* Python 3.10+
* Running [nnMCP](https://github.com/makeitworkok/nMCP) server

---

## License

MIT

---

Copyright (c) 2026 Chris Favre. All rights reserved.
