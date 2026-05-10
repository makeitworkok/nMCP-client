# Copyright (c) 2026 Chris Favre. All rights reserved.
"""Safety rules for tool execution.

Read-only tools execute immediately; write tools require explicit user approval.
"""

from __future__ import annotations

import re

# Prefixes that indicate a mutating / write operation
_WRITE_PREFIXES: tuple[str, ...] = (
    "create_",
    "delete_",
    "remove_",
    "update_",
    "set_",
    "write_",
    "link_",
    "wire_",
    "rename_",
    "modify_",
    "add_",
    "insert_",
    "replace_",
    "clear_",
    "reset_",
)

# Explicit tool names (in case the prefix heuristic misses them)
_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "create_point",
        "link_points",
        "create_wire",
        "delete_component",
        "rename_component",
        "update_point",
        "set_value",
    }
)


def is_write_tool(tool_name: str) -> bool:
    """Return True if *tool_name* represents a mutating operation."""
    lower = tool_name.lower()
    if lower in _WRITE_TOOL_NAMES:
        return True
    return any(lower.startswith(p) for p in _WRITE_PREFIXES)


def generate_explanation(tool_name: str, arguments: dict) -> str:
    """Produce a plain-English description of a proposed tool call."""
    # Format arguments into a human-readable sentence
    if not arguments:
        return f"Execute **{tool_name}** with no arguments."

    parts = []
    for k, v in arguments.items():
        readable_key = k.replace("_", " ")
        parts.append(f"{readable_key}: {v!r}")

    args_sentence = ", ".join(parts)
    tool_readable = tool_name.replace("_", " ").title()
    return f"{tool_readable} — {args_sentence}"


def categorise_tool(tool_name: str) -> str:
    """Return 'write' or 'read' for display purposes."""
    return "write" if is_write_tool(tool_name) else "read"
