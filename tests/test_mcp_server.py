from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_grb import make_fake_grok


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "plugins" / "grok-companion" / "scripts" / "mcp_server.py"
MCP_CONFIG = ROOT / "plugins" / "grok-companion" / ".mcp.json"


class McpClient:
    def __init__(self, env: dict[str, str]):
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=ROOT,
            env=env,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.next_id = 1

    def request(self, method: str, params: dict | None = None) -> dict:
        request_id = self.next_id
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            stderr = self.proc.stderr.read() if self.proc.stderr else ""
            raise AssertionError(f"MCP server exited without a response: {stderr}")
        response = json.loads(line)
        if response.get("id") != request_id:
            raise AssertionError(f"unexpected MCP response id: {response}")
        return response

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=5)
        if self.proc.stdout:
            self.proc.stdout.close()
        if self.proc.stderr:
            self.proc.stderr.close()


class McpServerTests(unittest.TestCase):
    def make_client(
        self,
        tmp: Path,
        *,
        sleep: float | None = None,
        read_stdin: bool = False,
        extra_env: dict[str, str] | None = None,
    ) -> McpClient:
        fake = make_fake_grok(tmp)
        env = {**os.environ, "GROK_BIN": str(fake)}
        if sleep is not None:
            env["GROK_FAKE_SLEEP"] = str(sleep)
        if read_stdin:
            env["GROK_FAKE_READ_STDIN"] = "1"
        env.update(extra_env or {})
        return McpClient(env)

    def initialize(self, client: McpClient) -> None:
        response = client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["result"]["serverInfo"]["name"], "grok-companion")

    def test_lists_native_grok_tools(self):
        with tempfile.TemporaryDirectory() as td:
            client = self.make_client(Path(td))
            try:
                self.initialize(client)
                response = client.request("tools/list")
                names = {tool["name"] for tool in response["result"]["tools"]}
                self.assertEqual(
                    names,
                    {
                        "grok_setup",
                        "grok_ask",
                        "grok_consult",
                        "grok_review",
                        "grok_adversarial_review",
                        "grok_research",
                        "grok_delegate",
                        "grok_continue",
                        "grok_sessions",
                        "grok_status",
                        "grok_wait",
                        "grok_result",
                        "grok_cancel",
                    },
                )
                resources = client.request("resources/list")
                self.assertEqual(resources["result"]["resources"], [])
                review_tool = next(tool for tool in response["result"]["tools"] if tool["name"] == "grok_review")
                properties = review_tool["inputSchema"]["properties"]
                self.assertEqual(properties["profile"]["enum"], ["full", "quick"])
                self.assertNotIn("default", properties["check"])
            finally:
                client.close()

    def test_plugin_forwards_local_proxy_environment(self):
        config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
        env_vars = config["mcpServers"]["grok-companion"]["env_vars"]
        self.assertIn("HTTP_PROXY", env_vars)
        self.assertIn("HTTPS_PROXY", env_vars)
        self.assertIn("ALL_PROXY", env_vars)
        self.assertIn("NO_PROXY", env_vars)
        self.assertIn("GROK_BIN", env_vars)

    def test_setup_does_not_inherit_mcp_json_rpc_stdin(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            client = self.make_client(tmp, read_stdin=True)
            try:
                self.initialize(client)
                response = client.request(
                    "tools/call",
                    {"name": "grok_setup", "arguments": {"cwd": str(tmp), "timeout": 2}},
                )["result"]
                self.assertFalse(response["isError"])
                self.assertEqual(response["structuredContent"]["status"], "ok")
            finally:
                client.close()

    def test_background_ask_status_and_result(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            client = self.make_client(tmp)
            try:
                self.initialize(client)
                launch = client.request(
                    "tools/call",
                    {
                        "name": "grok_ask",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "task": "-hello from MCP"},
                    },
                )["result"]
                self.assertFalse(launch["isError"])
                job_id = launch["structuredContent"]["job_id"]

                wait_response = client.request(
                    "tools/call",
                    {
                        "name": "grok_wait",
                        "arguments": {
                            "cwd": str(tmp),
                            "jobs_dir": str(jobs),
                            "job_id": job_id,
                            "timeout": 5,
                            "poll_interval_ms": 100,
                        },
                    },
                )["result"]
                self.assertFalse(wait_response["isError"])
                self.assertTrue(wait_response["structuredContent"]["completed"])
                self.assertEqual(wait_response["structuredContent"]["status"], "complete")

                result = client.request(
                    "tools/call",
                    {
                        "name": "grok_result",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": job_id},
                    },
                )["result"]
                self.assertFalse(result["isError"])
                self.assertIn("FAKE GROK RESULT", result["structuredContent"]["text"])
                prompt = (jobs / job_id / "prompt.md").read_text(encoding="utf-8")
                self.assertIn("-hello from MCP", prompt)
                self.assertNotIn("## Task\n\n-- -hello", prompt)
            finally:
                client.close()

    def test_mcp_profile_and_boolean_override_reach_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            client = self.make_client(tmp)
            try:
                self.initialize(client)
                launch = client.request(
                    "tools/call",
                    {
                        "name": "grok_review",
                        "arguments": {
                            "cwd": str(tmp),
                            "jobs_dir": str(jobs),
                            "task": "quick without check",
                            "profile": "quick",
                            "check": False,
                        },
                    },
                )["result"]["structuredContent"]
                waited = client.request(
                    "tools/call",
                    {
                        "name": "grok_wait",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": launch["job_id"], "timeout": 5},
                    },
                )["result"]
                self.assertFalse(waited["isError"])
                meta = json.loads((jobs / launch["job_id"] / "meta.json").read_text(encoding="utf-8"))
                raw = json.loads((jobs / launch["job_id"] / "raw.stdout").read_text(encoding="utf-8"))
                self.assertEqual((meta["profile"], meta["max_turns"], meta["timeout"], meta["check"]), ("quick", 6, 300, False))
                self.assertNotIn("--check", raw["argv"])
            finally:
                client.close()

    def test_mcp_omission_uses_full_mode_specific_self_check(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            client = self.make_client(tmp)
            try:
                self.initialize(client)
                for tool, expected_strategy, native_flag in (
                    ("grok_review", "prompt", False),
                    ("grok_research", "native", True),
                ):
                    jobs = tmp / f"jobs-{tool}"
                    launch = client.request(
                        "tools/call",
                        {"name": tool, "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "task": "default full"}},
                    )["result"]["structuredContent"]
                    waited = client.request(
                        "tools/call",
                        {
                            "name": "grok_wait",
                            "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": launch["job_id"], "timeout": 5},
                        },
                    )["result"]
                    self.assertFalse(waited["isError"])
                    job = jobs / launch["job_id"]
                    meta = json.loads((job / "meta.json").read_text(encoding="utf-8"))
                    raw = json.loads((job / "raw.stdout").read_text(encoding="utf-8"))
                    self.assertEqual((meta["profile"], meta["max_turns"], meta["timeout"], meta["check"]), ("full", 30, 3600, True))
                    self.assertEqual(meta["check_strategy"], expected_strategy)
                    self.assertEqual("--check" in raw["argv"], native_flag)
            finally:
                client.close()

    def test_wait_marks_failed_job_as_mcp_error(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            client = self.make_client(tmp, extra_env={"GROK_FAKE_REVIEW_MODE": "invalid"})
            try:
                self.initialize(client)
                launch = client.request(
                    "tools/call",
                    {
                        "name": "grok_review",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "task": "invalid"},
                    },
                )["result"]["structuredContent"]
                waited = client.request(
                    "tools/call",
                    {
                        "name": "grok_wait",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": launch["job_id"], "timeout": 5},
                    },
                )["result"]
                self.assertTrue(waited["isError"])
                self.assertTrue(waited["structuredContent"]["completed"])
                self.assertFalse(waited["structuredContent"]["job_ok"])
                self.assertEqual(waited["structuredContent"]["status"], "failed")
            finally:
                client.close()

    def test_cancel_can_run_while_wait_request_is_in_flight(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            client = self.make_client(tmp, sleep=10)
            try:
                self.initialize(client)
                launch = client.request(
                    "tools/call",
                    {
                        "name": "grok_ask",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "task": "slow"},
                    },
                )["result"]["structuredContent"]
                assert client.proc.stdin is not None
                assert client.proc.stdout is not None
                wait_message = {
                    "jsonrpc": "2.0",
                    "id": 1001,
                    "method": "tools/call",
                    "params": {
                        "name": "grok_wait",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": launch["job_id"], "timeout": 5},
                    },
                }
                cancel_message = {
                    "jsonrpc": "2.0",
                    "id": 1002,
                    "method": "tools/call",
                    "params": {
                        "name": "grok_cancel",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": launch["job_id"]},
                    },
                }
                client.proc.stdin.write(json.dumps(wait_message) + "\n")
                client.proc.stdin.write(json.dumps(cancel_message) + "\n")
                client.proc.stdin.flush()
                responses = {}
                deadline = time.time() + 8
                while len(responses) < 2 and time.time() < deadline:
                    response = json.loads(client.proc.stdout.readline())
                    responses[response["id"]] = response
                self.assertIn(1001, responses)
                self.assertIn(1002, responses)
                self.assertFalse(responses[1002]["result"]["isError"])
                self.assertTrue(responses[1002]["result"]["structuredContent"]["cancelled"])
                self.assertEqual(responses[1001]["result"]["structuredContent"]["status"], "cancelled")
            finally:
                client.close()

    def test_sessions_and_continue_are_native_tools(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            client = self.make_client(tmp)
            try:
                self.initialize(client)
                sessions = client.request(
                    "tools/call",
                    {"name": "grok_sessions", "arguments": {"cwd": str(tmp), "limit": 2}},
                )["result"]
                self.assertFalse(sessions["isError"])
                self.assertEqual(
                    sessions["structuredContent"]["session_ids"],
                    ["11111111-1111-4111-8111-111111111111"],
                )

                first = client.request(
                    "tools/call",
                    {
                        "name": "grok_ask",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "task": "first"},
                    },
                )["result"]["structuredContent"]
                client.request(
                    "tools/call",
                    {
                        "name": "grok_wait",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": first["job_id"], "timeout": 5},
                    },
                )
                continued = client.request(
                    "tools/call",
                    {
                        "name": "grok_continue",
                        "arguments": {
                            "cwd": str(tmp),
                            "jobs_dir": str(jobs),
                            "job_id": first["job_id"],
                            "task": "follow up",
                        },
                    },
                )["result"]
                self.assertFalse(continued["isError"])
                self.assertEqual(continued["structuredContent"]["status"], "running")
            finally:
                client.close()

    def test_cancel_terminates_background_process_group(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            client = self.make_client(tmp, sleep=10)
            try:
                self.initialize(client)
                launch = client.request(
                    "tools/call",
                    {
                        "name": "grok_research",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "task": "slow research"},
                    },
                )["result"]
                job_id = launch["structuredContent"]["job_id"]
                pid = launch["structuredContent"]["pid"]
                cancel = client.request(
                    "tools/call",
                    {
                        "name": "grok_cancel",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": job_id},
                    },
                )["result"]
                self.assertFalse(cancel["isError"])
                self.assertTrue(cancel["structuredContent"]["cancelled"])
                meta = json.loads((jobs / job_id / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(meta["status"], "cancelled")
                cancelled_result = json.loads((jobs / job_id / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(cancelled_result["status"], "cancelled")
                state = subprocess.run(
                    ["ps", "-o", "stat=", "-p", str(pid)],
                    text=True,
                    capture_output=True,
                    timeout=5,
                ).stdout.strip()
                self.assertTrue(not state or state.startswith("Z"), state)
            finally:
                client.close()

    def test_runner_cannot_overwrite_cancelled_terminal_state(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            jobs = tmp / "jobs"
            client = self.make_client(tmp, sleep=0.3)
            try:
                self.initialize(client)
                launch = client.request(
                    "tools/call",
                    {
                        "name": "grok_ask",
                        "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "task": "finish after cancellation"},
                    },
                )["result"]["structuredContent"]
                job_dir = jobs / launch["job_id"]
                meta_path = job_dir / "meta.json"
                deadline = time.time() + 5
                meta = None
                while time.time() < deadline:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if "command" in meta:
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(meta)
                meta["status"] = "cancelled"
                meta_path.write_text(json.dumps(meta), encoding="utf-8")

                while time.time() < deadline and not (job_dir / "result.json").exists():
                    time.sleep(0.05)
                final_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(final_meta["status"], "cancelled")
                self.assertEqual(result["status"], "cancelled")
            finally:
                client.close()

    def test_rejects_empty_cancel_id_and_removed_wait_argument(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            client = self.make_client(tmp)
            try:
                self.initialize(client)
                empty_id = client.request(
                    "tools/call",
                    {"name": "grok_cancel", "arguments": {"cwd": str(tmp), "job_id": ""}},
                )
                self.assertEqual(empty_id["error"]["code"], -32602)

                wait_arg = client.request(
                    "tools/call",
                    {"name": "grok_ask", "arguments": {"cwd": str(tmp), "task": "hello", "wait": True}},
                )
                self.assertEqual(wait_arg["error"]["code"], -32602)

                traversal = client.request(
                    "tools/call",
                    {"name": "grok_result", "arguments": {"cwd": str(tmp), "job_id": "../outside"}},
                )
                self.assertEqual(traversal["error"]["code"], -32602)
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
