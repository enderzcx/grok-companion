import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
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
            import os
            import sys
            import time
            from pathlib import Path

            if len(sys.argv) > 1 and sys.argv[1] == "version":
                print("grok fake 0.0.0")
                raise SystemExit(0)
            if len(sys.argv) > 1 and sys.argv[1] == "models":
                print("Default model: fake-grok")
                print("Available models:")
                print("  * fake-grok")
                raise SystemExit(0)

            if os.environ.get("GROK_FAKE_SLEEP"):
                time.sleep(float(os.environ["GROK_FAKE_SLEEP"]))

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

    def test_setup_degrades_when_grok_checks_fail(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fake = tmp / "broken-grok"
            fake.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
            fake.chmod(0o755)
            proc = subprocess.run(
                [sys.executable, str(GRB), "setup", "--json", "--jobs-dir", str(tmp / "jobs")],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=20,
                env={**os.environ, "GROK_BIN": str(fake)},
            )
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(json.loads(proc.stdout)["status"], "degraded")

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
            (tmp / "new.py").write_text("print('untracked')\n", encoding="utf-8")

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
            self.assertIn("new.py", prompt)
            self.assertIn("print('untracked')", prompt)

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

    def test_background_job_does_not_regress_after_fast_completion(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            launch = self.run_grb(tmp, "ask", "--jobs-dir", str(jobs), "--background", "fast")
            self.assertEqual(launch.returncode, 0, launch.stderr)
            job_id = json.loads(launch.stdout)["job_id"]
            deadline = time.time() + 5
            status = None
            while time.time() < deadline:
                proc = subprocess.run(
                    [sys.executable, str(GRB), "status", job_id, "--jobs-dir", str(jobs), "--json"],
                    cwd=tmp,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                status = json.loads(proc.stdout)[0]["status"]
                if status == "complete":
                    break
                time.sleep(0.05)
            self.assertEqual(status, "complete")

    def test_job_id_cannot_escape_jobs_directory(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            outside = tmp / "outside"
            jobs.mkdir()
            outside.mkdir()
            (outside / "meta.json").write_text(json.dumps({"job_id": "outside", "status": "complete"}), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(GRB), "result", "../outside", "--jobs-dir", str(jobs), "--json"],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Invalid job id", proc.stderr)

    def test_cancel_dead_pid_finalizes_cancelled_result(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            job = jobs / "job-dead-pid"
            job.mkdir(parents=True)
            (job / "meta.json").write_text(
                json.dumps({"job_id": "job-dead-pid", "status": "running", "pid": 2147483647}),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(GRB), "cancel", "job-dead-pid", "--jobs-dir", str(jobs), "--json"],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["cancelled"])
            result = json.loads((job / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
