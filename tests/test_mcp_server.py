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
    def make_client(self, tmp: Path, *, sleep: float | None = None, read_stdin: bool = False) -> McpClient:
        fake = make_fake_grok(tmp)
        env = {**os.environ, "GROK_BIN": str(fake)}
        if sleep is not None:
            env["GROK_FAKE_SLEEP"] = str(sleep)
        if read_stdin:
            env["GROK_FAKE_READ_STDIN"] = "1"
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
                        "grok_status",
                        "grok_result",
                        "grok_cancel",
                    },
                )
                resources = client.request("resources/list")
                self.assertEqual(resources["result"]["resources"], [])
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

                status = None
                deadline = time.time() + 5
                while time.time() < deadline:
                    status_response = client.request(
                        "tools/call",
                        {
                            "name": "grok_status",
                            "arguments": {"cwd": str(tmp), "jobs_dir": str(jobs), "job_id": job_id},
                        },
                    )["result"]
                    self.assertFalse(status_response["isError"])
                    status = status_response["structuredContent"]["jobs"][0]["status"]
                    if status == "complete":
                        break
                    time.sleep(0.05)
                self.assertEqual(status, "complete")

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
