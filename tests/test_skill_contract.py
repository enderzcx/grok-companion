from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "plugins" / "grok-companion" / "skills" / "grok-companion"
VALIDATOR = ROOT / "plugins" / "grok-companion" / "skills" / "grok-companion" / "scripts" / "validate.py"


class SkillContractTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )

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
        self.assertIn("same `job_id`", combined)
        self.assertIn("`job_ok: null`", combined)
        self.assertIn("wait_same_job", combined)
        self.assertIn("`grok_continue`", combined)
        self.assertIn("Do not cancel or restart", combined)
        self.assertNotIn("Call `grok_wait` once", combined)


if __name__ == "__main__":
    unittest.main()
