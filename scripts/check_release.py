#!/usr/bin/env python3
"""Validate public release metadata, dual packaging surfaces, and route-contract drift."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "grok-companion"
AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AGENT_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
PLUGIN_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SKILL_NAME_RE = re.compile(r"^(?!-)(?!.*--)[a-z0-9]+(?:-[a-z0-9]+)*(?<!-)$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - release checker wants exact path context
        fail(f"invalid JSON at {path.relative_to(ROOT)}: {exc}")
    raise AssertionError("unreachable")


def parse_frontmatter(skill_text: str) -> dict[str, object]:
    if not skill_text.startswith("---\n"):
        fail("SKILL.md must start with YAML frontmatter")
    end = skill_text.find("\n---\n", 4)
    if end < 0:
        fail("SKILL.md frontmatter is not closed")
    block = skill_text[4:end]
    data: dict[str, object] = {}
    metadata: dict[str, str] = {}
    in_metadata = False
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "metadata:":
            in_metadata = True
            continue
        if in_metadata and line.startswith("  ") and ":" in line:
            key, value = line.strip().split(":", 1)
            metadata[key.strip()] = value.strip().strip('"')
            continue
        in_metadata = False
        if ":" not in line:
            fail(f"unsupported frontmatter line: {line}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    if metadata:
        data["metadata"] = metadata
    return data


def check_agent_plugins_surface(version: str, plugin_name: str) -> None:
    portable = load_json(PLUGIN / "plugin.json")
    if not isinstance(portable, dict):
        fail("plugin.json must be an object")
    if portable.get("$schema") != AGENT_PLUGIN_SCHEMA:
        fail("plugin.json must declare the Agent Plugins 1.0.0 $schema")
    if portable.get("name") != plugin_name:
        fail("plugin.json name must match Codex plugin name")
    if portable.get("version") != version:
        fail("plugin.json version must match Codex plugin version")
    name = portable.get("name")
    if not isinstance(name, str) or not PLUGIN_NAME_RE.fullmatch(name) or len(name) > 64:
        fail("plugin.json name violates Agent Plugins naming rules")
    for field in ("description", "license", "homepage", "repository"):
        if field not in portable:
            fail(f"plugin.json missing recommended field: {field}")
    extensions = portable.get("extensions")
    if not isinstance(extensions, dict) or "com.openai.codex" not in extensions:
        fail("plugin.json must declare extensions.com.openai.codex for the Codex adapter")

    mcp = load_json(PLUGIN / "mcp.json")
    if not isinstance(mcp, dict):
        fail("mcp.json must be an object")
    if mcp.get("$schema") != AGENT_MCP_SCHEMA:
        fail("mcp.json must declare the Agent Plugins 1.0.0 MCP $schema")
    servers = mcp.get("mcpServers")
    if not isinstance(servers, dict) or "grok-companion" not in servers:
        fail("mcp.json must define mcpServers.grok-companion")
    server = servers["grok-companion"]
    if not isinstance(server, dict):
        fail("mcpServers.grok-companion must be an object")
    if server.get("type") != "stdio":
        fail("portable MCP server must use type=stdio")
    if server.get("command") != "python3":
        fail("portable MCP command must be python3")
    if server.get("args") != ["./scripts/mcp_server.py"]:
        fail("portable MCP args must point at ./scripts/mcp_server.py")
    if server.get("cwd") != "${PLUGIN_ROOT}":
        fail("portable MCP cwd must be ${PLUGIN_ROOT}")
    if "env" in server and not isinstance(server.get("env"), dict):
        fail("portable MCP env must be an object when present")

    codex_mcp = load_json(PLUGIN / ".mcp.json")
    if not isinstance(codex_mcp, dict):
        fail(".mcp.json must be an object")
    codex_servers = codex_mcp.get("mcpServers")
    if not isinstance(codex_servers, dict) or "grok-companion" not in codex_servers:
        fail(".mcp.json must define mcpServers.grok-companion")
    codex_server = codex_servers["grok-companion"]
    if not isinstance(codex_server, dict):
        fail(".mcp.json grok-companion must be an object")
    if codex_server.get("command") != server.get("command"):
        fail("Codex .mcp.json command drifted from portable mcp.json")
    if codex_server.get("args") != server.get("args"):
        fail("Codex .mcp.json args drifted from portable mcp.json")
    if codex_server.get("cwd") not in {".", "./", "${PLUGIN_ROOT}"}:
        fail("Codex .mcp.json cwd must resolve to the plugin root")
    env_vars = codex_server.get("env_vars")
    if not isinstance(env_vars, list) or "GROK_BIN" not in env_vars:
        fail("Codex .mcp.json must whitelist GROK_BIN in env_vars")


def check_skill_frontmatter(skill_text: str) -> None:
    frontmatter = parse_frontmatter(skill_text)
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
        fail("skill name violates Agent Skills naming rules")
    if name != "grok-companion":
        fail("skill name must match skills/grok-companion directory")
    if not isinstance(description, str) or not description or len(description) > 1024:
        fail("skill description must be 1-1024 characters")
    if "Use when" not in description and "explicitly asks" not in description:
        fail("skill description must include trigger language")
    if "Not for" not in description:
        fail("skill description must include exclusion language")
    compatibility = frontmatter.get("compatibility")
    if not isinstance(compatibility, str) or not compatibility or len(compatibility) > 500:
        fail("skill compatibility must be 1-500 characters")
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("agent_plugins") != "1.0.0":
        fail("skill metadata.agent_plugins must be 1.0.0")


def main() -> int:
    manifest = load_json(PLUGIN / ".codex-plugin" / "plugin.json")
    if not isinstance(manifest, dict):
        fail("Codex plugin.json must be an object")
    marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
    if not isinstance(marketplace, dict):
        fail("marketplace.json must be an object")
    grb = (PLUGIN / "scripts" / "grb.py").read_text(encoding="utf-8")
    server = (PLUGIN / "scripts" / "mcp_server.py").read_text(encoding="utf-8")
    skill = (PLUGIN / "skills" / "grok-companion" / "SKILL.md").read_text(encoding="utf-8")
    evals = load_json(PLUGIN / "skills" / "grok-companion" / "evals" / "trigger_cases.json")
    if not isinstance(evals, dict):
        fail("trigger_cases.json must be an object")
    schema = load_json(PLUGIN / "schemas" / "review-output.schema.json")
    if not isinstance(schema, dict):
        fail("review schema must be an object")
    monitor_template = PLUGIN / "skills" / "grok-companion" / "templates" / "job-monitor.html"

    version = manifest["version"]
    if not isinstance(version, str) or not version:
        fail("Codex plugin version is missing")
    marketplace_name = marketplace.get("name")
    plugin_name = manifest.get("name")
    if not isinstance(marketplace_name, str) or not marketplace_name:
        fail("marketplace name is missing")
    if not isinstance(plugin_name, str) or not plugin_name:
        fail("plugin name is missing")
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
        if "Agent Plugins" not in readme_text and "agent-plugins" not in readme_text:
            fail(f"{readme.name} must document the Agent Plugins portable surface")
    for label, text, pattern in (
        ("grb", grb, r'^VERSION = "([^"]+)"$'),
        ("mcp server", server, r'^SERVER_VERSION = "([^"]+)"$'),
    ):
        match = re.search(pattern, text, re.MULTILINE)
        if not match or match.group(1) != version:
            fail(f"{label} version does not match plugin manifest {version}")
    if 'cmd.append("--check")' in grb or 'return "native"' in grb:
        fail("grb must keep Companion self-check in prompts instead of forwarding Grok CLI --check")

    check_agent_plugins_surface(version, plugin_name)
    check_skill_frontmatter(skill)

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

    for relative in (
        "plugins/grok-companion/plugin.json",
        "plugins/grok-companion/mcp.json",
        "plugins/grok-companion/.mcp.json",
        "plugins/grok-companion/.codex-plugin/plugin.json",
        "docs/AGENT_PLUGINS.md",
        "docs/PUBLIC_SKILL_PLUGIN_PUBLISHING.md",
    ):
        path = ROOT / relative
        if not path.is_file():
            fail(f"required packaging file missing: {relative}")

    validator = PLUGIN / "skills" / "grok-companion" / "scripts" / "validate.py"
    proc = subprocess.run([sys.executable, str(validator), "validate"], text=True, capture_output=True)
    if proc.returncode != 0:
        fail(f"installed skill validation failed: {proc.stderr.strip() or proc.stdout.strip()}")
    for readme in (ROOT / "README.md", ROOT / "README.en.md"):
        if f"v{version}" not in readme.read_text(encoding="utf-8"):
            fail(f"{readme.name} does not mention v{version}")

    print(
        f"release check: ok ({version}, agent-plugins dual surface, "
        f"{len(cases)} route cases, {len(required_tools)} MCP tools)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
