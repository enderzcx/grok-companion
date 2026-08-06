from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "plugins" / "grok-companion" / "skills" / "grok-companion"
VALIDATOR = ROOT / "plugins" / "grok-companion" / "skills" / "grok-companion" / "scripts" / "validate.py"


class SkillContractTests(unittest.TestCase):
    PLUGIN = ROOT / "plugins" / "grok-companion"

    def run_validator(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_agent_plugins_portable_surface(self):
        portable = json.loads((self.PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        codex = json.loads((self.PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        mcp = json.loads((self.PLUGIN / "mcp.json").read_text(encoding="utf-8"))
        codex_mcp = json.loads((self.PLUGIN / ".mcp.json").read_text(encoding="utf-8"))

        self.assertEqual(
            portable["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        )
        self.assertEqual(portable["name"], codex["name"])
        self.assertEqual(portable["version"], codex["version"])
        self.assertIn("com.openai.codex", portable["extensions"])

        self.assertEqual(
            mcp["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        )
        portable_server = mcp["mcpServers"]["grok-companion"]
        codex_server = codex_mcp["mcpServers"]["grok-companion"]
        self.assertEqual(portable_server["type"], "stdio")
        self.assertEqual(portable_server["command"], codex_server["command"])
        self.assertEqual(portable_server["args"], codex_server["args"])
        self.assertEqual(portable_server["cwd"], "${PLUGIN_ROOT}")
        self.assertIn("GROK_BIN", codex_server["env_vars"])

        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('agent_plugins: "1.0.0"', skill)
        self.assertIn("license: MIT", skill)

    def test_list_exposes_only_bounded_sop_files(self):
        proc = self.run_validator("list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SKILL.md", proc.stdout)
        self.assertIn("references/routing.md", proc.stdout)
        self.assertIn("templates/review-result.json", proc.stdout)
        self.assertIn("templates/job-monitor.html", proc.stdout)
        self.assertNotIn("scripts/validate.py", proc.stdout)

    def test_read_allows_sop_and_rejects_escape(self):
        readable = self.run_validator("read", "references/routing.md")
        self.assertEqual(readable.returncode, 0, readable.stderr)
        self.assertIn("Does Not Own", readable.stdout)

        escaped = self.run_validator("read", "../scripts/grb.py")
        self.assertNotEqual(escaped.returncode, 0)
        self.assertIn("dot-segment", escaped.stderr)

    def test_validate_checks_installed_plugin_contract(self):
        proc = self.run_validator("validate")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("14 MCP tools", proc.stdout)

    def test_skill_requires_full_context_wait_and_session_continuity(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        handling = (SKILL_DIR / "references" / "result-handling.md").read_text(encoding="utf-8")
        combined = skill + "\n" + handling
        self.assertIn("profile=full", combined)
        self.assertIn("no plugin-imposed turn cap", combined)
        self.assertIn("effort `xhigh`", combined)
        self.assertIn("512000", combined)
        self.assertIn("stay uncapped unless the caller explicitly supplies `max_turns`", combined)
        self.assertIn("same `job_id`", combined)
        self.assertIn("`job_ok: null`", combined)
        self.assertIn("wait_same_job", combined)
        self.assertIn("`grok_continue`", combined)
        self.assertIn("Do not cancel or restart", combined)
        self.assertNotIn("Call `grok_wait` once", combined)

    def test_skill_supports_opt_in_host_policy_routing(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        routing = (SKILL_DIR / "references" / "routing.md").read_text(encoding="utf-8")
        combined = skill + "\n" + routing
        self.assertIn("active host policy", combined)
        self.assertIn("pre-authorizes automatic collaborator selection", combined)
        self.assertIn("🧭 route:", combined)
        self.assertIn("general task complexity is not authorization", combined)
        self.assertIn("exact allowed writes", combined)

    def test_trigger_evals_cover_policy_selection_and_disqualifiers(self):
        cases = json.loads(
            (SKILL_DIR / "evals" / "trigger_cases.json").read_text(encoding="utf-8")
        )["cases"]
        implicit_delegate = next(case for case in cases if case["id"] == "host-policy-bounded-builder")
        self.assertTrue(implicit_delegate["should_trigger"])
        self.assertEqual(implicit_delegate["route"], "grok_delegate")
        self.assertTrue(implicit_delegate["expects_route_marker"])
        self.assertNotIn("Grok", implicit_delegate["prompt"])

        disqualified = [
            case for case in cases if case.get("activation") == "host-policy-disqualified"
        ]
        self.assertGreaterEqual(len(disqualified), 3)
        self.assertTrue(all(case["should_trigger"] is False for case in disqualified))
        self.assertTrue(all(case["expects_skip_reason"] is True for case in disqualified))


if __name__ == "__main__":
    unittest.main()
