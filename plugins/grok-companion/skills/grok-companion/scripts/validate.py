#!/usr/bin/env python3
"""Validate the installed Grok Companion plugin and skill contract."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
PLUGIN = SKILL.parents[1]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def allowed_sop_files() -> dict[str, Path]:
    files = {"SKILL.md": SKILL / "SKILL.md"}
    for folder_name in ("references", "templates", "evals"):
        folder = SKILL / folder_name
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    files[path.relative_to(SKILL).as_posix()] = path
    return files


def validate() -> int:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    grb = (PLUGIN / "scripts" / "grb.py").read_text(encoding="utf-8")
    server = (PLUGIN / "scripts" / "mcp_server.py").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    evals = json.loads((SKILL / "evals" / "trigger_cases.json").read_text(encoding="utf-8"))
    schema = json.loads((PLUGIN / "schemas" / "review-output.schema.json").read_text(encoding="utf-8"))
    template = json.loads((SKILL / "templates" / "review-result.json").read_text(encoding="utf-8"))

    version = manifest["version"]
    for label, text, pattern in (
        ("grb", grb, r'^VERSION = "([^"]+)"$'),
        ("mcp server", server, r'^SERVER_VERSION = "([^"]+)"$'),
    ):
        match = re.search(pattern, text, re.MULTILINE)
        if not match or match.group(1) != version:
            fail(f"{label} version does not match plugin manifest {version}")

    required_tools = {
        "grok_setup", "grok_ask", "grok_consult", "grok_review",
        "grok_adversarial_review", "grok_research", "grok_delegate",
        "grok_continue", "grok_sessions", "grok_status", "grok_wait",
        "grok_result", "grok_cancel",
    }
    missing = sorted(name for name in required_tools if f'"name": "{name}"' not in server)
    if missing:
        fail(f"MCP tool definitions missing: {', '.join(missing)}")

    cases = evals.get("cases")
    if not isinstance(cases, list) or not any(case.get("should_trigger") is True for case in cases):
        fail("routing evals need positive cases")
    if not any(case.get("should_trigger") is False for case in cases):
        fail("routing evals need negative cases")
    if "Use when" not in skill or "Not for" not in skill:
        fail("skill frontmatter is missing explicit trigger or exclusion language")
    if schema.get("required") != ["verdict", "summary", "findings", "next_steps"]:
        fail("review schema required fields drifted")
    if not set(schema["required"]).issubset(template):
        fail("review result template is missing required schema fields")

    print(f"grok-companion validate: ok ({version}, {len(cases)} route cases, {len(required_tools)} MCP tools)")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if command == "list":
        for relative in allowed_sop_files():
            print(relative)
        return 0
    if command == "read":
        if len(sys.argv) != 3:
            fail("usage: validate.py read <SKILL.md|references/...|evals/...>")
        relative = sys.argv[2]
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            fail("absolute paths and dot-segment escapes are not allowed")
        path = allowed_sop_files().get(relative)
        if path is None:
            fail(f"SOP path is not agent-readable: {relative}")
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if command == "validate":
        return validate()
    fail(f"unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
