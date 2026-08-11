from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GRB = ROOT / "plugins" / "grok-companion" / "scripts" / "grb.py"


def load_grb_module():
    spec = spec_from_file_location("grok_companion_grb", GRB)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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

            if os.environ.get("GROK_FAKE_READ_STDIN"):
                sys.stdin.read()

            if len(sys.argv) > 1 and sys.argv[1] == "version":
                print("grok fake 0.0.0")
                raise SystemExit(0)
            if len(sys.argv) > 1 and sys.argv[1] == "models":
                print("Default model: fake-grok")
                print("Available models:")
                print("  * fake-grok")
                raise SystemExit(0)
            if len(sys.argv) > 2 and sys.argv[1:3] in (["sessions", "list"], ["sessions", "search"]):
                print("SESSION ID                            CREATED     UPDATED     STATUS      SUMMARY")
                session = os.environ.get("GROK_FAKE_SESSION_ID", "11111111-1111-4111-8111-111111111111")
                print(f"{session}  2026-07-12  2026-07-12  local  Fake session")
                raise SystemExit(0)

            argv_log = os.environ.get("GROK_FAKE_ARGV_LOG")
            if argv_log:
                with Path(argv_log).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(sys.argv[1:]) + "\\n")

            transport_counter = os.environ.get("GROK_FAKE_TRANSPORT_COUNTER")
            if transport_counter:
                counter_path = Path(transport_counter)
                count = int(counter_path.read_text(encoding="utf-8")) if counter_path.exists() else 0
                counter_path.write_text(str(count + 1), encoding="utf-8")
                if count < int(os.environ.get("GROK_FAKE_TRANSPORT_FAILURES", "1")):
                    message = 'Internal error: "reqwest error stream: error sending request for url (https://cli-chat-proxy.grok.com/v1/responses)"'
                    print(json.dumps({"type": "error", "message": message}))
                    print(f"Error: {message}", file=sys.stderr)
                    raise SystemExit(1)

            if os.environ.get("GROK_FAKE_SLEEP"):
                time.sleep(float(os.environ["GROK_FAKE_SLEEP"]))

            prompt = ""
            if "--prompt-file" in sys.argv:
                idx = sys.argv.index("--prompt-file")
                prompt = Path(sys.argv[idx + 1]).read_text(encoding="utf-8")
            if "--json-schema" in sys.argv:
                review = {
                    "verdict": "approve",
                    "summary": "Fake structured review passed.",
                    "findings": [],
                    "next_steps": ["Run the test suite."]
                }
                review_mode = os.environ.get("GROK_FAKE_REVIEW_MODE", "text")
                if review_mode == "invalid":
                    review["findings"] = [{"severity": "nope"}]
                text = "structured review envelope" if review_mode == "structured-only" else json.dumps(review)
            else:
                text = "FAKE GROK RESULT\\n" + prompt[:120]
            payload = {
                "text": text,
                "argv": sys.argv[1:]
            }
            if "--json-schema" in sys.argv and os.environ.get("GROK_FAKE_REVIEW_MODE") in {"structured-only", "invalid"}:
                payload["structuredOutput"] = review
            if not os.environ.get("GROK_FAKE_NO_SESSION"):
                payload["sessionId"] = "11111111-1111-4111-8111-111111111111"
            print(json.dumps(payload))
            raise SystemExit(int(os.environ.get("GROK_FAKE_EXIT", "0")))
            """
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


class GrbTests(unittest.TestCase):
    def run_grb(self, tmp: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        fake = make_fake_grok(tmp)
        env = {**os.environ, "GROK_BIN": str(fake), **(extra_env or {})}
        return subprocess.run(
            [sys.executable, str(GRB), *args],
            cwd=tmp,
            text=True,
            capture_output=True,
            timeout=20,
            env=env,
        )

    def test_setup_reports_fake_grok(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            proc = self.run_grb(tmp, "setup", "--json", "--jobs-dir", str(tmp / "jobs"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["checks"]["grok_version"]["ok"])

    def test_macos_system_proxy_fallback_populates_empty_environment(self):
        grb = load_grb_module()
        output = """\
<dictionary> {
  ExceptionsList : <array> {
    0 : 127.0.0.1
    1 : localhost
    2 : *.local
  }
  HTTPEnable : 1
  HTTPPort : 7890
  HTTPProxy : 127.0.0.1
  HTTPSEnable : 1
  HTTPSPort : 7890
  HTTPSProxy : 127.0.0.1
  SOCKSEnable : 1
  SOCKSPort : 7890
  SOCKSProxy : 127.0.0.1
}
"""
        completed = subprocess.CompletedProcess(["scutil", "--proxy"], 0, output, "")
        env = {}
        with mock.patch.object(grb.sys, "platform", "darwin"), mock.patch.object(
            grb.subprocess, "run", return_value=completed
        ):
            source = grb.apply_system_proxy_fallback(env)
        self.assertEqual(source, "macos-system")
        self.assertEqual(env["HTTP_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(env["ALL_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(env["NO_PROXY"], "127.0.0.1,localhost,*.local")

    def test_explicit_proxy_environment_skips_system_fallback(self):
        grb = load_grb_module()
        env = {"HTTPS_PROXY": "http://explicit.invalid:8080"}
        with mock.patch.object(grb.subprocess, "run") as run:
            source = grb.apply_system_proxy_fallback(env)
        self.assertEqual(source, "environment")
        self.assertEqual(env, {"HTTPS_PROXY": "http://explicit.invalid:8080"})
        run.assert_not_called()

    def test_setup_discovers_standard_user_install_without_host_path(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            home = tmp / "home"
            grok = home / ".local" / "bin" / "grok"
            grok.parent.mkdir(parents=True)
            grok.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = version ]; then echo 'grok local 0.0.0'; exit 0; fi\n"
                "if [ \"$1\" = models ]; then echo 'Default model: fake-grok'; exit 0; fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            grok.chmod(0o755)
            env = {**os.environ, "HOME": str(home), "PATH": "/usr/bin:/bin"}
            env.pop("GROK_BIN", None)
            proc = subprocess.run(
                [sys.executable, str(GRB), "setup", "--json", "--jobs-dir", str(tmp / "jobs")],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=20,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["grok_bin"], str(grok))
            self.assertEqual(payload["grok_path"], str(grok))
            self.assertEqual(payload["status"], "ok")

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

    def test_setup_serializes_partial_bytes_after_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fake = tmp / "slow-grok"
            fake.write_text(
                "#!/usr/bin/env python3\nimport os, time\nos.write(1, b'partial output')\ntime.sleep(2)\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(GRB),
                    "setup",
                    "--json",
                    "--timeout",
                    "1",
                    "--jobs-dir",
                    str(tmp / "jobs"),
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=10,
                env={**os.environ, "GROK_BIN": str(fake)},
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "degraded")
            self.assertEqual(payload["checks"]["grok_version"]["stdout"], "partial output")
            self.assertIsInstance(payload["checks"]["grok_models"]["stderr"], str)

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
            self.assertEqual(meta["result_session_id"], "11111111-1111-4111-8111-111111111111")

    def test_full_profile_is_default_and_resolves_by_mode(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for mode, expected_check in (
                ("ask", False),
                ("review", True),
                ("adversarial-review", True),
                ("research", True),
            ):
                jobs = tmp / f"jobs-{mode}"
                proc = self.run_grb(tmp, mode, "--jobs-dir", str(jobs), "profile defaults")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                job = next(jobs.iterdir())
                meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
                raw = json.loads((job / "raw.stdout").read_text(encoding="utf-8"))
                self.assertEqual(meta["profile"], "full")
                self.assertIsNone(meta["max_turns"])
                self.assertEqual(meta["timeout"], 7200)
                self.assertEqual(meta["effort"], "high")
                self.assertEqual(meta["check"], expected_check)
                self.assertNotIn("--max-turns", raw["argv"])
                self.assertEqual(raw["argv"][raw["argv"].index("--effort") + 1], "high")
                expected_strategy = "prompt" if mode in {"review", "adversarial-review"} else "native" if expected_check else "off"
                self.assertEqual(meta["check_strategy"], expected_strategy)
                self.assertEqual("--check" in raw["argv"], mode == "research")
                prompt = (job / "prompt.md").read_text(encoding="utf-8")
                self.assertEqual("Self-Check Contract" in prompt, expected_strategy == "prompt")

    def test_quick_profile_and_explicit_runtime_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            quick_jobs = tmp / "quick-jobs"
            quick = self.run_grb(tmp, "research", "--profile", "quick", "--jobs-dir", str(quick_jobs), "quick")
            self.assertEqual(quick.returncode, 0, quick.stderr)
            quick_job = next(quick_jobs.iterdir())
            quick_meta = json.loads((quick_job / "meta.json").read_text(encoding="utf-8"))
            quick_raw = json.loads((quick_job / "raw.stdout").read_text(encoding="utf-8"))
            self.assertEqual((quick_meta["max_turns"], quick_meta["timeout"], quick_meta["effort"], quick_meta["check"]), (16, 900, "high", False))
            self.assertNotIn("--check", quick_raw["argv"])

            override_jobs = tmp / "override-jobs"
            overridden = self.run_grb(
                tmp,
                "review",
                "--profile",
                "quick",
                "--max-turns",
                "45",
                "--timeout",
                "7200",
                "--effort",
                "low",
                "--check",
                "--jobs-dir",
                str(override_jobs),
                "explicit overrides",
            )
            self.assertEqual(overridden.returncode, 0, overridden.stderr)
            override_job = next(override_jobs.iterdir())
            override_meta = json.loads((override_job / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual((override_meta["max_turns"], override_meta["timeout"], override_meta["effort"], override_meta["check"]), (45, 7200, "low", True))
            self.assertEqual(override_meta["check_strategy"], "prompt")
            override_raw = json.loads((override_job / "raw.stdout").read_text(encoding="utf-8"))
            self.assertNotIn("--check", override_raw["argv"])
            self.assertEqual(override_raw["argv"][override_raw["argv"].index("--effort") + 1], "low")

            no_check_jobs = tmp / "no-check-jobs"
            no_check = self.run_grb(tmp, "review", "--no-check", "--jobs-dir", str(no_check_jobs), "force off")
            self.assertEqual(no_check.returncode, 0, no_check.stderr)
            no_check_job = next(no_check_jobs.iterdir())
            no_check_meta = json.loads((no_check_job / "meta.json").read_text(encoding="utf-8"))
            no_check_raw = json.loads((no_check_job / "raw.stdout").read_text(encoding="utf-8"))
            self.assertFalse(no_check_meta["check"])
            self.assertNotIn("--check", no_check_raw["argv"])

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
            result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["review"]["verdict"], "approve")
            self.assertIn("No actionable findings", (job_dir / "result.md").read_text(encoding="utf-8"))

    def test_review_prefers_live_structured_output_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            proc = self.run_grb(
                tmp,
                "review",
                "--jobs-dir",
                str(jobs),
                "review envelope",
                extra_env={"GROK_FAKE_REVIEW_MODE": "structured-only"},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads((next(jobs.iterdir()) / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["review"]["summary"], "Fake structured review passed.")
            self.assertIsNone(result["contract_error"])

    def test_malformed_review_fails_with_contract_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            proc = self.run_grb(
                tmp,
                "review",
                "--jobs-dir",
                str(jobs),
                "invalid review",
                extra_env={"GROK_FAKE_REVIEW_MODE": "invalid"},
            )
            self.assertEqual(proc.returncode, 2)
            job = next(jobs.iterdir())
            result = json.loads((job / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["returncode"], 2)
            self.assertEqual(result["grok_returncode"], 0)
            self.assertIn("structured review contract", result["contract_error"])
            self.assertIn("nope", (job / "raw.stdout").read_text(encoding="utf-8"))

    def test_review_retries_retryable_transport_failure_within_same_job(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            counter = tmp / "transport-count"
            argv_log = tmp / "argv.jsonl"
            proc = self.run_grb(
                tmp,
                "review",
                "--jobs-dir",
                str(jobs),
                "retry transport",
                extra_env={
                    "GROK_FAKE_TRANSPORT_COUNTER": str(counter),
                    "GROK_FAKE_TRANSPORT_FAILURES": "1",
                    "GROK_FAKE_ARGV_LOG": str(argv_log),
                },
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            job = next(jobs.iterdir())
            result = json.loads((job / "result.json").read_text(encoding="utf-8"))
            meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["review"]["verdict"], "approve")
            self.assertEqual(len(result["attempt_details"]), 2)
            self.assertTrue(result["attempt_details"][0]["retryable_transport_error"])
            self.assertTrue(result["attempt_details"][0]["will_retry"])
            self.assertFalse(result["attempt_details"][1]["retryable_transport_error"])
            self.assertFalse(result["attempt_details"][1]["will_retry"])
            self.assertEqual(meta["transport_retries"], 2)
            self.assertEqual(meta["transport_retry_strategy"], "resume-finalize")
            retry_session = meta["transport_retry_session_id"]
            self.assertRegex(retry_session, r"^[0-9a-f-]{36}$")
            first_argv, retry_argv = [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines()]
            self.assertIn("--session-id", first_argv)
            self.assertEqual(first_argv[first_argv.index("--session-id") + 1], retry_session)
            self.assertEqual(retry_argv, result["parsed"]["argv"])
            self.assertIn("--resume", result["parsed"]["argv"])
            self.assertEqual(result["parsed"]["argv"][result["parsed"]["argv"].index("--resume") + 1], retry_session)
            self.assertEqual(result["parsed"]["argv"][result["parsed"]["argv"].index("--tools") + 1], "")
            self.assertIn("transport-retry-prompt.md", result["parsed"]["argv"][result["parsed"]["argv"].index("--prompt-file") + 1])
            self.assertEqual(result["attempt_details"][1]["strategy"], "resume-finalize")
            self.assertTrue((job / "attempt-1.stderr").exists())
            self.assertTrue((job / "attempt-2.stdout").exists())

    def test_exhausted_review_transport_retries_preserve_primary_error(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            counter = tmp / "transport-count"
            proc = self.run_grb(
                tmp,
                "review",
                "--transport-retries",
                "1",
                "--jobs-dir",
                str(jobs),
                "exhaust transport retry",
                extra_env={
                    "GROK_FAKE_TRANSPORT_COUNTER": str(counter),
                    "GROK_FAKE_TRANSPORT_FAILURES": "5",
                },
            )
            self.assertEqual(proc.returncode, 1)
            job = next(jobs.iterdir())
            result = json.loads((job / "result.json").read_text(encoding="utf-8"))
            meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(result["error_kind"], "transport")
            self.assertFalse(result["retryable"])
            self.assertIsNone(result["contract_error"])
            self.assertEqual(len(result["attempt_details"]), 2)
            self.assertFalse(result["attempt_details"][-1]["will_retry"])
            self.assertIn("reqwest error stream", meta["error"])
            self.assertEqual(result["session_id"], meta["transport_retry_session_id"])
            self.assertEqual(meta["result_session_id"], meta["transport_retry_session_id"])

            continued = self.run_grb(
                tmp,
                "continue",
                "--jobs-dir",
                str(jobs),
                "--job-id",
                job.name,
                "finish after operator follow-up",
            )
            self.assertEqual(continued.returncode, 0, continued.stderr)
            continued_job = sorted(jobs.iterdir())[-1]
            continued_raw = json.loads((continued_job / "raw.stdout").read_text(encoding="utf-8"))
            self.assertEqual(
                continued_raw["argv"][continued_raw["argv"].index("--resume") + 1],
                meta["transport_retry_session_id"],
            )

    def test_resume_finalize_timeout_preserves_attempt_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            counter = tmp / "transport-count"
            proc = self.run_grb(
                tmp,
                "review",
                "--transport-retries",
                "1",
                "--timeout",
                "4",
                "--jobs-dir",
                str(jobs),
                "timeout during finalization",
                extra_env={
                    "GROK_FAKE_TRANSPORT_COUNTER": str(counter),
                    "GROK_FAKE_TRANSPORT_FAILURES": "1",
                    "GROK_FAKE_SLEEP": "10",
                },
            )
            self.assertEqual(proc.returncode, 124)
            job = next(jobs.iterdir())
            result = json.loads((job / "result.json").read_text(encoding="utf-8"))
            meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "timeout")
            self.assertEqual(result["error_kind"], "timeout")
            self.assertFalse(result["retryable"])
            self.assertEqual(len(result["attempt_details"]), 2)
            self.assertTrue(result["attempt_details"][1]["timed_out"])
            self.assertEqual(result["attempt_details"][1]["strategy"], "resume-finalize")
            self.assertEqual(result["session_id"], meta["transport_retry_session_id"])
            self.assertTrue((job / "attempt-2.stdout").exists())
            self.assertIn("job deadline", (job / "attempt-2.stderr").read_text(encoding="utf-8"))

    def test_post_transport_invalid_review_is_contract_failure(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            counter = tmp / "transport-count"
            proc = self.run_grb(
                tmp,
                "review",
                "--transport-retries",
                "1",
                "--jobs-dir",
                str(jobs),
                "invalid recovery payload",
                extra_env={
                    "GROK_FAKE_TRANSPORT_COUNTER": str(counter),
                    "GROK_FAKE_TRANSPORT_FAILURES": "1",
                    "GROK_FAKE_REVIEW_MODE": "invalid",
                },
            )
            self.assertEqual(proc.returncode, 2)
            result = json.loads((next(jobs.iterdir()) / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["error_kind"], "contract")
            self.assertIn("structured review contract", result["contract_error"])
            self.assertIsNone(result["retryable"])
            self.assertIn("reqwest error stream", result["attempt_details"][0]["error"])

    def test_insufficient_deadline_records_unstarted_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            counter = tmp / "transport-count"
            proc = self.run_grb(
                tmp,
                "review",
                "--transport-retries",
                "1",
                "--timeout",
                "2",
                "--jobs-dir",
                str(jobs),
                "no recovery budget",
                extra_env={
                    "GROK_FAKE_TRANSPORT_COUNTER": str(counter),
                    "GROK_FAKE_TRANSPORT_FAILURES": "1",
                },
            )
            self.assertEqual(proc.returncode, 1)
            result = json.loads((next(jobs.iterdir()) / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["error_kind"], "transport")
            self.assertEqual(len(result["attempt_details"]), 2)
            skipped = result["attempt_details"][1]
            self.assertFalse(skipped["started"])
            self.assertTrue(skipped["timed_out"])
            self.assertEqual(skipped["strategy"], "resume-finalize")
            self.assertIn("insufficient remaining time", skipped["error"])
            self.assertEqual(result["recoveries_not_started"], 1)

    def test_non_review_transport_failure_is_not_retried_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            counter = tmp / "transport-count"
            proc = self.run_grb(
                tmp,
                "ask",
                "--transport-retries",
                "2",
                "--jobs-dir",
                str(jobs),
                "do not retry ask",
                extra_env={
                    "GROK_FAKE_TRANSPORT_COUNTER": str(counter),
                    "GROK_FAKE_TRANSPORT_FAILURES": "1",
                },
            )
            self.assertEqual(proc.returncode, 1)
            job = next(jobs.iterdir())
            result = json.loads((job / "result.json").read_text(encoding="utf-8"))
            meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["transport_retries"], 0)
            self.assertEqual(len(result["attempt_details"]), 1)

    def test_missing_review_schema_becomes_durable_failure(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            copied = tmp / "plugin" / "scripts" / "grb.py"
            copied.parent.mkdir(parents=True)
            shutil.copy2(GRB, copied)
            fake = make_fake_grok(tmp)
            jobs = tmp / "jobs"
            proc = subprocess.run(
                [sys.executable, str(copied), "review", "--jobs-dir", str(jobs), "missing schema"],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=20,
                env={**os.environ, "GROK_BIN": str(fake)},
            )
            self.assertEqual(proc.returncode, 78)
            job = next(jobs.iterdir())
            result = json.loads((job / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")
            self.assertIn("review schema unavailable", result["contract_error"])

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

    def test_monitor_renders_terminal_snapshot_and_escapes_embedded_json(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            ask = self.run_grb(tmp, "ask", "--jobs-dir", str(jobs), "monitor me")
            self.assertEqual(ask.returncode, 0, ask.stderr)
            job = next(jobs.iterdir())
            result_path = job / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["text"] = "safe </script><script>unsafe()</script>"
            result_path.write_text(json.dumps(result), encoding="utf-8")
            output = tmp / "grok-job.html"
            monitor = subprocess.run(
                [
                    sys.executable,
                    str(GRB),
                    "monitor",
                    job.name,
                    "--jobs-dir",
                    str(jobs),
                    "--output",
                    str(output),
                    "--json",
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=20,
            )
            self.assertEqual(monitor.returncode, 0, monitor.stderr)
            payload = json.loads(monitor.stdout)
            self.assertTrue(payload["snapshot"]["terminal"])
            self.assertTrue(payload["snapshot"]["job_ok"])
            self.assertIn("continue", payload["snapshot"]["actions"])
            html = output.read_text(encoding="utf-8")
            self.assertIn("\\u003c/script\\u003e", html)
            self.assertNotIn("</script><script>unsafe", html)
            self.assertNotIn("__GROK_MONITOR_JSON__", html)

            watched = subprocess.run(
                [sys.executable, str(GRB), "watch", job.name, "--jobs-dir", str(jobs), "--once", "--json"],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=20,
            )
            self.assertEqual(watched.returncode, 0, watched.stderr)
            self.assertEqual(json.loads(watched.stdout)["status"], "complete")

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

    def test_wait_returns_terminal_result_without_status_polling(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            launch = self.run_grb(tmp, "ask", "--jobs-dir", str(jobs), "--background", "wait for me")
            job_id = json.loads(launch.stdout)["job_id"]
            waited = subprocess.run(
                [sys.executable, str(GRB), "wait", job_id, "--jobs-dir", str(jobs), "--timeout", "5", "--json"],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(waited.returncode, 0, waited.stderr)
            payload = json.loads(waited.stdout)
            self.assertTrue(payload["completed"])
            self.assertEqual(payload["status"], "complete")
            self.assertIs(payload["job_ok"], True)
            self.assertEqual(payload["next_action"], "read_result")
            self.assertIn("FAKE GROK RESULT", payload["result"]["text"])

    def test_wait_marks_running_job_as_pending_not_failed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            launch = self.run_grb(
                tmp,
                "ask",
                "--jobs-dir",
                str(jobs),
                "--background",
                "keep running",
                extra_env={"GROK_FAKE_SLEEP": "2"},
            )
            job_id = json.loads(launch.stdout)["job_id"]
            waited = subprocess.run(
                [sys.executable, str(GRB), "wait", job_id, "--jobs-dir", str(jobs), "--timeout", "0", "--json"],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(waited.returncode, 0, waited.stderr)
            payload = json.loads(waited.stdout)
            self.assertFalse(payload["completed"])
            self.assertIsNone(payload["job_ok"])
            self.assertEqual(payload["next_action"], "wait_same_job")

    def test_sessions_and_continue_resume_discovered_job_session(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            first = self.run_grb(tmp, "ask", "--jobs-dir", str(jobs), "first question")
            self.assertEqual(first.returncode, 0, first.stderr)
            first_job = next(jobs.iterdir()).name

            continued = self.run_grb(
                tmp,
                "continue",
                "--jobs-dir",
                str(jobs),
                "--job-id",
                first_job,
                "follow up",
            )
            self.assertEqual(continued.returncode, 0, continued.stderr)
            latest = sorted(jobs.iterdir())[-1]
            raw = json.loads((latest / "raw.stdout").read_text(encoding="utf-8"))
            meta = json.loads((latest / "meta.json").read_text(encoding="utf-8"))
            self.assertIn("--resume", raw["argv"])
            self.assertIn("11111111-1111-4111-8111-111111111111", raw["argv"])
            self.assertEqual((meta["profile"], meta["max_turns"], meta["timeout"], meta["effort"], meta["check"]), ("full", None, 7200, "high", False))
            self.assertNotIn("--max-turns", raw["argv"])

            sessions = self.run_grb(tmp, "sessions", "--json")
            self.assertEqual(sessions.returncode, 0, sessions.stderr)
            self.assertEqual(json.loads(sessions.stdout)["session_ids"], ["11111111-1111-4111-8111-111111111111"])

            named = self.run_grb(
                tmp,
                "sessions",
                "--json",
                extra_env={"GROK_FAKE_SESSION_ID": "session-local-2026"},
            )
            self.assertEqual(json.loads(named.stdout)["session_ids"], ["session-local-2026"])

    def test_continue_without_recoverable_session_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            first = self.run_grb(
                tmp,
                "ask",
                "--jobs-dir",
                str(jobs),
                "no session",
                extra_env={"GROK_FAKE_NO_SESSION": "1"},
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            job_id = next(jobs.iterdir()).name
            continued = self.run_grb(
                tmp,
                "continue",
                "--jobs-dir",
                str(jobs),
                "--job-id",
                job_id,
                "follow up",
                extra_env={"GROK_FAKE_NO_SESSION": "1"},
            )
            self.assertNotEqual(continued.returncode, 0)
            self.assertIn("No resumable Grok session", continued.stderr)

    def test_wait_recovers_orphan_result_and_terminalizes_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            recovered = jobs / "job-recovered"
            recovered.mkdir(parents=True)
            (recovered / "meta.json").write_text(
                json.dumps({"job_id": "job-recovered", "status": "running", "pid": 2147483647}),
                encoding="utf-8",
            )
            (recovered / "result.json").write_text(
                json.dumps({"job_id": "job-recovered", "status": "complete", "returncode": 0, "text": "saved"}),
                encoding="utf-8",
            )
            waited = subprocess.run(
                [sys.executable, str(GRB), "wait", "job-recovered", "--jobs-dir", str(jobs), "--timeout", "1", "--json"],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=5,
            )
            payload = json.loads(waited.stdout)
            self.assertTrue(payload["completed"])
            self.assertIs(payload["job_ok"], True)
            self.assertEqual(payload["next_action"], "read_result")
            self.assertEqual(payload["result"]["text"], "saved")

            unknown = jobs / "job-unknown"
            unknown.mkdir()
            (unknown / "meta.json").write_text(
                json.dumps(
                    {
                        "job_id": "job-unknown",
                        "status": "running",
                        "pid": 2147483647,
                        "created_at": "2026-07-13T00:00:00+00:00",
                        "started_at": "2026-07-13T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            unknown_wait = subprocess.run(
                [sys.executable, str(GRB), "wait", "job-unknown", "--jobs-dir", str(jobs), "--timeout", "1", "--json"],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=5,
            )
            unknown_payload = json.loads(unknown_wait.stdout)
            self.assertNotEqual(unknown_wait.returncode, 0)
            self.assertTrue(unknown_payload["completed"])
            self.assertIs(unknown_payload["job_ok"], False)
            self.assertEqual(unknown_payload["next_action"], "inspect_failure")
            self.assertEqual(unknown_payload["status"], "unknown")
            unknown_meta = json.loads((unknown / "meta.json").read_text(encoding="utf-8"))
            self.assertIsNotNone(unknown_meta["finished_at"])

            snapshots = []
            for _ in range(2):
                status = subprocess.run(
                    [
                        sys.executable,
                        str(GRB),
                        "status",
                        "job-unknown",
                        "--jobs-dir",
                        str(jobs),
                        "--detail",
                        "monitor",
                        "--json",
                    ],
                    cwd=tmp,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                envelope = json.loads(status.stdout)
                self.assertEqual(envelope["detail"], "monitor")
                snapshots.append(envelope["snapshot"])
                time.sleep(0.01)
            self.assertEqual(snapshots[0]["elapsed_seconds"], snapshots[1]["elapsed_seconds"])
            self.assertNotIn("result", snapshots[0]["actions"])

            legacy = jobs / "job-legacy-terminal"
            legacy.mkdir()
            (legacy / "meta.json").write_text(
                json.dumps(
                    {
                        "job_id": "job-legacy-terminal",
                        "status": "unknown",
                        "created_at": "2026-07-13T00:00:00+00:00",
                        "updated_at": "2026-07-13T00:01:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            legacy_status = subprocess.run(
                [
                    sys.executable,
                    str(GRB),
                    "status",
                    "job-legacy-terminal",
                    "--jobs-dir",
                    str(jobs),
                    "--detail",
                    "monitor",
                    "--json",
                ],
                cwd=tmp,
                text=True,
                capture_output=True,
                timeout=5,
            )
            legacy_snapshot = json.loads(legacy_status.stdout)["snapshot"]
            self.assertEqual(legacy_snapshot["finished_at"], "2026-07-13T00:01:00+00:00")
            self.assertEqual(legacy_snapshot["elapsed_seconds"], 60.0)

    def test_monitor_rejects_output_outside_workspace_or_codex_visualizations(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            ask = self.run_grb(tmp, "ask", "--jobs-dir", str(jobs), "monitor boundaries")
            self.assertEqual(ask.returncode, 0, ask.stderr)
            job_id = next(jobs.iterdir()).name
            for output in (tmp / "monitor.txt", tmp.parent / f"outside-{tmp.name}.html"):
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(GRB),
                        "monitor",
                        job_id,
                        "--jobs-dir",
                        str(jobs),
                        "--output",
                        str(output),
                    ],
                    cwd=tmp,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertFalse(output.exists())

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
