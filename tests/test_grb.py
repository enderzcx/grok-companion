import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRB = ROOT / "plugins" / "grok-companion" / "scripts" / "grb.py"


def make_fake_grok(tmp: Path) -> Path:
    fake = tmp / "fake-grok"
    fake.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys
            from pathlib import Path

            if len(sys.argv) > 1 and sys.argv[1] == "version":
                print("grok fake 0.0.0")
                raise SystemExit(0)
            if len(sys.argv) > 1 and sys.argv[1] == "models":
                print("Default model: fake-grok")
                print("Available models:")
                print("  * fake-grok")
                raise SystemExit(0)

            prompt = ""
            if "--prompt-file" in sys.argv:
                idx = sys.argv.index("--prompt-file")
                prompt = Path(sys.argv[idx + 1]).read_text(encoding="utf-8")
            print(json.dumps({"text": "FAKE GROK RESULT\\n" + prompt[:120]}))
            """
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


class GrbTests(unittest.TestCase):
    def run_grb(self, tmp: Path, *args: str) -> subprocess.CompletedProcess:
        fake = make_fake_grok(tmp)
        return subprocess.run(
            [sys.executable, str(GRB), *args],
            cwd=tmp,
            text=True,
            capture_output=True,
            timeout=20,
            env={**os.environ, "GROK_BIN": str(fake)},
        )

    def test_setup_reports_fake_grok(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            proc = self.run_grb(tmp, "setup", "--json", "--jobs-dir", str(tmp / "jobs"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["checks"]["grok_version"]["ok"])

    def test_ask_creates_result_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            proc = self.run_grb(
                tmp,
                "ask",
                "--jobs-dir",
                str(jobs),
                "--max-turns",
                "1",
                "hello from codex",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("FAKE GROK RESULT", proc.stdout)
            job_dirs = list(jobs.iterdir())
            self.assertEqual(len(job_dirs), 1)
            self.assertTrue((job_dirs[0] / "prompt.md").exists())
            self.assertTrue((job_dirs[0] / "result.md").exists())
            meta = json.loads((job_dirs[0] / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], "complete")

    def test_review_includes_git_context(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            subprocess.run(["git", "init"], cwd=tmp, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
            (tmp / "app.py").write_text("print('one')\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=tmp, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, check=True, capture_output=True)
            (tmp / "app.py").write_text("print('two')\n", encoding="utf-8")

            jobs = tmp / "jobs"
            proc = self.run_grb(
                tmp,
                "review",
                "--jobs-dir",
                str(jobs),
                "--max-turns",
                "1",
                "review current diff",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            job_dir = next(jobs.iterdir())
            prompt = (job_dir / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Review Contract", prompt)
            self.assertIn("app.py", prompt)

    def test_result_reads_latest_job(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            ask = self.run_grb(tmp, "ask", "--jobs-dir", str(jobs), "hello")
            self.assertEqual(ask.returncode, 0, ask.stderr)
            result = subprocess.run(
                [sys.executable, str(GRB), "result", "--jobs-dir", str(jobs)],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("FAKE GROK RESULT", result.stdout)


if __name__ == "__main__":
    unittest.main()
