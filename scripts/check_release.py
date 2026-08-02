#!/usr/bin/env python3
"""Validate public release metadata and route-contract drift."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "grok-companion"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
    grb = (PLUGIN / "scripts" / "grb.py").read_text(encoding="utf-8")
    server = (PLUGIN / "scripts" / "mcp_server.py").read_text(encoding="utf-8")
    skill = (PLUGIN / "skills" / "grok-companion" / "SKILL.md").read_text(encoding="utf-8")
    evals = json.loads((PLUGIN / "skills" / "grok-companion" / "evals" / "trigger_cases.json").read_text(encoding="utf-8"))
    schema = json.loads((PLUGIN / "schemas" / "review-output.schema.json").read_text(encoding="utf-8"))
    monitor_template = PLUGIN / "skills" / "grok-companion" / "templates" / "job-monitor.html"

    version = manifest["version"]
    marketplace_name = marketplace.get("name")
    plugin_name = manifest.get("name")
    if not isinstance(marketplace_name, str) or not marketplace_name:
        fail("marketplace name is missing")
    if marketplace_name == plugin_name:
        fail("marketplace and plugin names must differ to avoid duplicate cache path segments")
    current_selector = f"{plugin_name}@{marketplace_name}"
    legacy_selector = f"{plugin_name}@{plugin_name}"
    for readme in (ROOT / "README.md", ROOT / "README.en.md"):
        readme_text = readme.read_text(encoding="utf-8")
        if current_selector not in readme_text:
            fail(f"{readme.name} does not contain current install selector {current_selector}")
        if readme_text.count(legacy_selector) != 1:
            fail(f"{readme.name} must contain legacy selector exactly once in migration removal instructions")
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
        "grok_continue", "grok_sessions", "grok_status", "grok_monitor", "grok_wait",
        "grok_result", "grok_cancel",
    }
    missing = sorted(name for name in required_tools if f'"name": "{name}"' not in server)
    if missing:
        fail(f"MCP tool definitions missing: {', '.join(missing)}")

    cases = evals.get("cases")
    if not isinstance(cases, list) or not cases:
        fail("trigger evals must contain cases")
    if not any(case.get("should_trigger") is True for case in cases):
        fail("trigger evals need positive cases")
    if not any(case.get("should_trigger") is False for case in cases):
        fail("trigger evals need negative cases")
    for route in ("superx", "native-review", "named-other-collaborator"):
        if not any(case.get("route") == route and case.get("should_trigger") is False for case in cases):
            fail(f"trigger evals missing negative route: {route}")
    if not any(
        case.get("activation") == "host-policy"
        and case.get("route") == "grok_delegate"
        and case.get("should_trigger") is True
        and case.get("expects_route_marker") is True
        for case in cases
    ):
        fail("trigger evals missing visible host-policy delegation route")
    if not any(
        case.get("activation") == "host-policy-disqualified"
        and case.get("should_trigger") is False
        and case.get("expects_skip_reason") is True
        for case in cases
    ):
        fail("trigger evals missing host-policy disqualifier with skip receipt")

    if (
        "explicitly asks" not in skill
        or "active host policy" not in skill
        or "🧭 route:" not in skill
        or "exact X/Twitter" not in skill
        or "generic code review" not in skill
    ):
        fail("skill frontmatter/body is missing trigger or exclusion language")
    if schema.get("required") != ["verdict", "summary", "findings", "next_steps"]:
        fail("review schema required fields drifted")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(monitor_template.relative_to(ROOT))],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if tracked.returncode != 0:
        fail("job monitor template is not tracked by git")

    validator = PLUGIN / "skills" / "grok-companion" / "scripts" / "validate.py"
    proc = subprocess.run([sys.executable, str(validator), "validate"], text=True, capture_output=True)
    if proc.returncode != 0:
        fail(f"installed skill validation failed: {proc.stderr.strip() or proc.stdout.strip()}")
    for readme in (ROOT / "README.md", ROOT / "README.en.md"):
        if f"v{version}" not in readme.read_text(encoding="utf-8"):
            fail(f"{readme.name} does not mention v{version}")

    print(f"release check: ok ({version}, {len(cases)} route cases, {len(required_tools)} MCP tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
