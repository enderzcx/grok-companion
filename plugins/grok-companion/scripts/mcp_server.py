#!/usr/bin/env python3
"""Dependency-free stdio MCP adapter for Grok Companion."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


SERVER_NAME = "grok-companion"
SERVER_VERSION = "0.4.3"
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", PROTOCOL_VERSION}
GRB = Path(__file__).with_name("grb.py").resolve()
WRITE_LOCK = threading.Lock()


def object_schema(
    properties: dict[str, Any],
    required: list[str] | None = None,
    *,
    additional_properties: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = required
    return schema


CWD = {
    "type": "string",
    "description": "Absolute path of the current Codex workspace or repository.",
}
JOBS_DIR = {
    "type": "string",
    "description": "Optional job directory override. Defaults to <cwd>/.grok-companion/jobs.",
}
RUNTIME_PROPERTIES: dict[str, Any] = {
    "task": {"type": "string", "minLength": 1, "description": "The complete task or question for Grok."},
    "cwd": CWD,
    "jobs_dir": JOBS_DIR,
    "model": {"type": "string", "description": "Optional Grok model id."},
    "effort": {"type": "string", "enum": ["low", "medium", "high", "xhigh", "max"]},
    "reasoning_effort": {"type": "string"},
    "profile": {
        "type": "string",
        "enum": ["full", "quick"],
        "description": "Runtime profile. Omission defaults to full: 30 turns and a 3600-second job timeout.",
    },
    "max_turns": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Explicit profile override."},
    "timeout": {"type": "integer", "minimum": 1, "maximum": 86400, "description": "Job runtime in seconds, not the grok_wait budget."},
    "tools": {"type": "string", "description": "Comma-separated Grok tool allowlist."},
    "disallowed_tools": {"type": "string", "description": "Comma-separated Grok tool denylist."},
    "disable_web_search": {"type": "boolean", "default": False},
    "check": {"type": "boolean", "description": "Explicit self-check override. When omitted, full enables it for review, adversarial review, and research. Structured reviews use a prompt self-check because Grok CLI rejects --check with --json-schema."},
    "best_of_n": {"type": "integer", "minimum": 1, "maximum": 32},
    "session_id": {"type": "string", "description": "Existing Grok session id to resume with grok --resume."},
}


def launch_schema(*, git_context: bool = False, base: bool = False) -> dict[str, Any]:
    properties = dict(RUNTIME_PROPERTIES)
    if git_context:
        properties["include_git_context"] = {"type": "boolean", "default": False}
    if base:
        properties["base"] = {"type": "string", "description": "Git base ref, for example main."}
    return object_schema(properties, ["task", "cwd"])


TOOLS: list[dict[str, Any]] = [
    {
        "name": "grok_setup",
        "description": "Check the local Grok CLI, login-visible models, job directory, and optional superx diagnostics.",
        "inputSchema": object_schema(
            {
                "cwd": CWD,
                "jobs_dir": JOBS_DIR,
                "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "default": 30},
                "probe_superx": {"type": "boolean", "default": False},
            },
            ["cwd"],
        ),
    },
    {
        "name": "grok_ask",
        "description": "Ask Grok a general question as a background job; use grok_status and grok_result afterward.",
        "inputSchema": launch_schema(git_context=True, base=True),
    },
    {
        "name": "grok_consult",
        "description": "Get Grok's second opinion on a plan, decision, or implementation as a background job.",
        "inputSchema": launch_schema(git_context=True, base=True),
    },
    {
        "name": "grok_review",
        "description": "Run a read-only Grok code review over the working tree or base...HEAD. Findings only; Grok must not edit files.",
        "inputSchema": launch_schema(base=True),
    },
    {
        "name": "grok_adversarial_review",
        "description": "Run a read-only Grok challenge review focused on architecture, assumptions, failure modes, and alternatives.",
        "inputSchema": launch_schema(base=True),
    },
    {
        "name": "grok_research",
        "description": "Start a source-aware Grok research job. For exact X/Twitter retrieval use superx instead.",
        "inputSchema": launch_schema(git_context=True, base=True),
    },
    {
        "name": "grok_delegate",
        "description": "Delegate a bounded task to the full local Grok CLI. This may use tools or edit files; invoke only when the user or an active host policy authorized the exact write boundary.",
        "inputSchema": launch_schema(git_context=True, base=True),
    },
    {
        "name": "grok_continue",
        "description": "Continue a prior Grok conversation using an explicit session_id, a companion job_id, or the latest resumable companion job.",
        "inputSchema": object_schema(
            {
                **RUNTIME_PROPERTIES,
                "job_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$", "description": "Companion job whose returned Grok session should be resumed."},
                "include_git_context": {"type": "boolean", "default": False},
                "base": {"type": "string", "description": "Optional git base ref when including git context."},
            },
            ["task", "cwd"],
        ),
    },
    {
        "name": "grok_sessions",
        "description": "List or search sessions known to the local Grok CLI and return discovered session ids.",
        "inputSchema": object_schema(
            {
                "cwd": CWD,
                "query": {"type": "string", "description": "Optional search query over Grok session summaries and first prompts."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "default": 30},
            },
            ["cwd"],
        ),
    },
    {
        "name": "grok_status",
        "description": "List recent Grok jobs or inspect one job. detail=monitor returns a rich status snapshot without claiming live token streaming.",
        "inputSchema": object_schema(
            {
                "cwd": CWD,
                "job_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
                "jobs_dir": JOBS_DIR,
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                "detail": {"type": "string", "enum": ["summary", "monitor"], "default": "summary"},
                "tail_chars": {"type": "integer", "minimum": 0, "maximum": 20000, "default": 4000},
            },
            ["cwd"],
        ),
    },
    {
        "name": "grok_monitor",
        "description": "Render a Grok job snapshot as a Codex inline visualization HTML file. Refresh by calling the tool again for the same job and output path.",
        "inputSchema": object_schema(
            {
                "cwd": CWD,
                "job_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
                "jobs_dir": JOBS_DIR,
                "output": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Absolute .html output path inside cwd or the current Codex visualization directory.",
                },
                "tail_chars": {"type": "integer", "minimum": 0, "maximum": 20000, "default": 4000},
            },
            ["cwd", "output"],
        ),
    },
    {
        "name": "grok_result",
        "description": "Return the stored result for a completed Grok job, or the latest job when job_id is omitted.",
        "inputSchema": object_schema(
            {
                "cwd": CWD,
                "job_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
                "jobs_dir": JOBS_DIR,
            },
            ["cwd"],
        ),
    },
    {
        "name": "grok_wait",
        "description": "Perform one bounded wait for a Grok job. An incomplete response has job_ok=null and next_action=wait_same_job; call grok_wait again with the same job_id and never restart or cancel merely because a wait elapsed.",
        "inputSchema": object_schema(
            {
                "cwd": CWD,
                "job_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
                "jobs_dir": JOBS_DIR,
                "timeout": {"type": "integer", "minimum": 0, "maximum": 300, "default": 90},
                "poll_interval_ms": {"type": "integer", "minimum": 50, "maximum": 5000, "default": 250},
            },
            ["cwd"],
        ),
    },
    {
        "name": "grok_cancel",
        "description": "Cancel a running Grok background job and its process tree.",
        "inputSchema": object_schema(
            {
                "cwd": CWD,
                "job_id": {"type": "string", "minLength": 1, "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
                "jobs_dir": JOBS_DIR,
            },
            ["cwd", "job_id"],
        ),
    },
]


def resolve_cwd(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("cwd is required")
    cwd = Path(value).expanduser().resolve()
    if not cwd.is_dir():
        raise ValueError(f"cwd is not a directory: {cwd}")
    return cwd


def add_option(cmd: list[str], args: dict[str, Any], key: str, flag: str | None = None) -> None:
    value = args.get(key)
    if value is None or value is False or value == "":
        return
    option = flag or "--" + key.replace("_", "-")
    if value is True:
        cmd.append(option)
    else:
        cmd.extend([option, str(value)])


def terminated_process_payload(returncode: int) -> dict[str, Any] | None:
    if returncode >= 0:
        return None
    signal_number = -returncode
    try:
        signal_name = signal.Signals(signal_number).name
    except ValueError:
        signal_name = f"SIGNAL_{signal_number}"
    return {
        "status": "failed",
        "error": "grb_terminated_by_signal",
        "returncode": returncode,
        "signal": signal_number,
        "signal_name": signal_name,
        "retry_safe": False,
        "message": (
            f"grb was terminated by signal {signal_number} ({signal_name}) before it completed cleanly. "
            "This is not a Grok job timeout. Check the same cwd and jobs_dir for an existing job before "
            "retrying; if no job exists, restart Codex App to rebuild the MCP process."
        ),
    }


def invoke_grb(cwd: Path, args: list[str]) -> tuple[int, Any, str, str]:
    proc = subprocess.run(
        [sys.executable, str(GRB), *args],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
    )
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    payload: Any = stdout
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            pass
    terminated = terminated_process_payload(proc.returncode)
    if terminated is not None:
        if isinstance(payload, dict):
            payload = {**payload, **terminated}
        else:
            if stdout:
                terminated["stdout_tail"] = stdout[-4000:]
            payload = terminated
    return proc.returncode, payload, stdout, stderr


def launch_tool(name: str, args: dict[str, Any]) -> tuple[int, Any, str, str]:
    mode = name.removeprefix("grok_").replace("adversarial_review", "adversarial-review")
    cwd = resolve_cwd(args.get("cwd"))
    cmd = [mode]
    for key in (
        "jobs_dir",
        "model",
        "effort",
        "reasoning_effort",
        "profile",
        "max_turns",
        "timeout",
        "tools",
        "disallowed_tools",
        "disable_web_search",
        "best_of_n",
        "session_id",
        "job_id",
        "include_git_context",
        "base",
    ):
        add_option(cmd, args, key)
    if args.get("check") is True:
        cmd.append("--check")
    elif args.get("check") is False:
        cmd.append("--no-check")
    cmd.append("--background")
    cmd.extend(["--format", "json", "--", args["task"]])
    return invoke_grb(cwd, cmd)


def call_tool(name: str, args: dict[str, Any]) -> tuple[int, Any, str, str]:
    if name in {
        "grok_ask",
        "grok_consult",
        "grok_review",
        "grok_adversarial_review",
        "grok_research",
        "grok_delegate",
        "grok_continue",
    }:
        return launch_tool(name, args)

    cwd = resolve_cwd(args.get("cwd"))
    if name == "grok_setup":
        cmd = ["setup", "--json"]
        add_option(cmd, args, "jobs_dir")
        add_option(cmd, args, "timeout")
        add_option(cmd, args, "probe_superx")
        return invoke_grb(cwd, cmd)
    if name == "grok_status":
        cmd = ["status"]
        if args.get("job_id"):
            cmd.append(str(args["job_id"]))
        add_option(cmd, args, "jobs_dir")
        add_option(cmd, args, "limit")
        add_option(cmd, args, "detail")
        add_option(cmd, args, "tail_chars")
        cmd.append("--json")
        return invoke_grb(cwd, cmd)
    if name == "grok_monitor":
        output = Path(str(args["output"])).expanduser()
        if not output.is_absolute():
            raise ValueError("output must be an absolute path")
        cmd = ["monitor"]
        if args.get("job_id"):
            cmd.append(str(args["job_id"]))
        add_option(cmd, args, "jobs_dir")
        cmd.extend(["--output", str(output)])
        add_option(cmd, args, "tail_chars")
        cmd.append("--json")
        return invoke_grb(cwd, cmd)
    if name == "grok_sessions":
        cmd = ["sessions"]
        if args.get("query"):
            cmd.append(str(args["query"]))
        add_option(cmd, args, "limit")
        add_option(cmd, args, "timeout")
        cmd.append("--json")
        return invoke_grb(cwd, cmd)
    if name == "grok_wait":
        cmd = ["wait"]
        if args.get("job_id"):
            cmd.append(str(args["job_id"]))
        add_option(cmd, args, "jobs_dir")
        add_option(cmd, args, "timeout")
        if args.get("poll_interval_ms") is not None:
            cmd.extend(["--poll-interval", str(args["poll_interval_ms"] / 1000)])
        cmd.append("--json")
        return invoke_grb(cwd, cmd)
    if name == "grok_result":
        cmd = ["result"]
        if args.get("job_id"):
            cmd.append(str(args["job_id"]))
        add_option(cmd, args, "jobs_dir")
        cmd.append("--json")
        return invoke_grb(cwd, cmd)
    if name == "grok_cancel":
        cmd = ["cancel", str(args.get("job_id") or "")]
        add_option(cmd, args, "jobs_dir")
        cmd.append("--json")
        return invoke_grb(cwd, cmd)
    raise ValueError(f"unknown tool: {name}")


def validate_tool_arguments(name: str, arguments: dict[str, Any]) -> None:
    tool = next((item for item in TOOLS if item["name"] == name), None)
    if tool is None:
        raise ValueError(f"unknown tool: {name}")
    schema = tool["inputSchema"]
    properties = schema.get("properties", {})
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ValueError(f"unknown argument(s) for {name}: {', '.join(unknown)}")
    for key in schema.get("required", []):
        if key not in arguments or arguments[key] is None or arguments[key] == "":
            raise ValueError(f"{key} is required for {name}")
    for key, value in arguments.items():
        definition = properties[key]
        expected = definition.get("type")
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        if expected == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"{key} must be an integer")
        if isinstance(value, str) and len(value) < definition.get("minLength", 0):
            raise ValueError(f"{key} is too short")
        if isinstance(value, str) and "pattern" in definition and re.fullmatch(definition["pattern"], value) is None:
            raise ValueError(f"{key} has an invalid format")
        if isinstance(value, int) and not isinstance(value, bool):
            if "minimum" in definition and value < definition["minimum"]:
                raise ValueError(f"{key} must be at least {definition['minimum']}")
            if "maximum" in definition and value > definition["maximum"]:
                raise ValueError(f"{key} must be at most {definition['maximum']}")
        if "enum" in definition and value not in definition["enum"]:
            raise ValueError(f"{key} must be one of: {', '.join(definition['enum'])}")


def tool_result(code: int, payload: Any, stdout: str, stderr: str) -> dict[str, Any]:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = str(payload or stdout or stderr or f"grb exited with code {code}")
    terminal_job_error = isinstance(payload, dict) and payload.get("completed") is True and payload.get("job_ok") is False
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": code != 0 or terminal_job_error,
    }
    if isinstance(payload, dict):
        result["structuredContent"] = payload
    elif isinstance(payload, list):
        result["structuredContent"] = {"jobs": payload}
    if stderr:
        result.setdefault("_meta", {})["stderr"] = stderr[-4000:]
    return result


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    try:
        if method == "initialize":
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("initialize params must be an object")
            requested = params.get("protocolVersion")
            negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
            return {
                "id": request_id,
                "result": {
                    "protocolVersion": negotiated,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "instructions": (
                        "Grok launch tools always use background jobs. Pass the current workspace as cwd, "
                        "then repeat bounded grok_wait calls with the same job_id until terminal. An incomplete wait "
                        "uses job_ok=null and next_action=wait_same_job; it does not justify cancellation or restart. "
                        "Only terminal job_ok=false is a job failure. Full is the default runtime profile; quick is opt-in. "
                        "Use grok_monitor for a refreshable inline job snapshot, and grok_sessions plus grok_continue "
                        "for continuity. Use superx for exact X/Twitter retrieval."
                    ),
                },
            }
        if method == "ping":
            return {"id": request_id, "result": {}}
        if method == "tools/list":
            return {"id": request_id, "result": {"tools": TOOLS}}
        if method == "resources/list":
            return {"id": request_id, "result": {"resources": []}}
        if method == "resources/templates/list":
            return {"id": request_id, "result": {"resourceTemplates": []}}
        if method == "tools/call":
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise ValueError("tool params must be an object")
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str):
                raise ValueError("tool name is required")
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            validate_tool_arguments(name, arguments)
            code, payload, stdout, stderr = call_tool(name, arguments)
            return {"id": request_id, "result": tool_result(code, payload, stdout, stderr)}
        return {
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    except (KeyError, TypeError, ValueError) as exc:
        return {"id": request_id, "error": {"code": -32602, "message": str(exc)}}
    except Exception as exc:  # Keep protocol failures visible without killing the server.
        return {"id": request_id, "error": {"code": -32603, "message": f"Internal error: {exc}"}}


def write_message(message: dict[str, Any]) -> None:
    message.setdefault("jsonrpc", "2.0")
    with WRITE_LOCK:
        sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def process_message(message: dict[str, Any]) -> None:
    response = handle_request(message)
    if response is not None:
        write_message(response)


def main() -> int:
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="grok-mcp") as executor:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("JSON-RPC message must be an object")
                executor.submit(process_message, message)
            except (json.JSONDecodeError, ValueError) as exc:
                write_message({"id": None, "error": {"code": -32700, "message": str(exc)}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
