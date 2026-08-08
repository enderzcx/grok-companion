#!/usr/bin/env python3
"""Grok Companion bridge for local agents.

This script is intentionally standalone: Codex can run it directly from the
plugin skill, and tests can exercise it with a fake grok binary.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path
from shutil import which
from typing import Any


VERSION = "0.4.5"
DEFAULT_PROFILE = "full"
# full = complete Grok collaborator budget (no artificial turn starve, high reasoning, long runtime).
# quick = connectivity / deliberately short tasks only.
#
# Effort defaults are pinned to levels accepted by the current default model (grok-4.5):
# live CLI 0.2.118 accepts only high|medium|low for that model. Canonical CLI docs also list
# xhigh/max, but those fail at launch when the active model menu does not advertise them.
PROFILE_DEFAULTS = {
    "full": {"max_turns": None, "timeout": 7200, "effort": "high"},
    "quick": {"max_turns": 16, "timeout": 900, "effort": "high"},
}
AUTO_CHECK_MODES = {"review", "adversarial-review", "research"}
# All full-profile modes leave max_turns unset unless the caller overrides; structured
# reviews also stay uncapped under quick unless max_turns is explicit.
UNBOUNDED_REVIEW_MODES = {"review", "adversarial-review"}
DEFAULT_TIMEOUT = PROFILE_DEFAULTS[DEFAULT_PROFILE]["timeout"]
DEFAULT_MAX_TURNS = PROFILE_DEFAULTS[DEFAULT_PROFILE]["max_turns"]
# Embedded git/diff packet size in characters. 80k was too small for multi-file reviews;
# 256k matches the order of codex-plugin-cc's inline-diff budget. This is NOT Grok's full
# model context window — oversized packets still waste tokens and can crowd tools/system
# prompt. When truncated, the prompt tells Grok to tool-read the remainder.
DEFAULT_CONTEXT_LIMIT = 256_000
DEFAULT_WAIT_TIMEOUT = 180.0
JOB_ROOT_NAME = ".grok-companion"
TERMINAL_STATUSES = {"complete", "failed", "timeout", "cancelled", "unknown"}
REVIEW_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "review-output.schema.json"
MONITOR_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "skills" / "grok-companion" / "templates" / "job-monitor.html"
PROXY_ENV_NAMES = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
}


class ReviewSchemaError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def repo_or_cwd() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return Path.cwd().resolve()


def default_jobs_dir() -> Path:
    env = os.environ.get("GROK_COMPANION_JOBS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return repo_or_cwd() / JOB_ROOT_NAME / "jobs"


def default_grok_bin() -> str:
    configured = os.environ.get("GROK_BIN")
    if configured:
        return str(Path(configured).expanduser()) if os.path.isabs(os.path.expanduser(configured)) else configured

    discovered = which("grok")
    if discovered:
        return discovered

    for candidate in (Path.home() / ".local" / "bin" / "grok", Path.home() / ".grok" / "bin" / "grok"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    return "grok"


def parse_macos_system_proxy(output: str) -> dict[str, str]:
    """Translate enabled `scutil --proxy` entries into standard proxy env vars."""

    def value(name: str) -> str | None:
        match = re.search(rf"^\s*{re.escape(name)}\s*:\s*(.*?)\s*$", output, re.MULTILINE)
        return match.group(1) if match else None

    def endpoint(prefix: str, scheme: str = "http") -> str | None:
        if value(f"{prefix}Enable") != "1":
            return None
        host = value(f"{prefix}Proxy")
        port = value(f"{prefix}Port")
        if not host or not port or not port.isdigit():
            return None
        return f"{scheme}://{host}:{port}"

    http_proxy = endpoint("HTTP")
    https_proxy = endpoint("HTTPS") or http_proxy
    socks_proxy = endpoint("SOCKS", "socks5h")
    fallback_proxy = https_proxy or http_proxy or socks_proxy
    if not fallback_proxy:
        return {}

    proxies: dict[str, str] = {}
    if http_proxy:
        proxies.update({"HTTP_PROXY": http_proxy, "http_proxy": http_proxy})
    if https_proxy:
        proxies.update({"HTTPS_PROXY": https_proxy, "https_proxy": https_proxy})
    proxies.update({"ALL_PROXY": fallback_proxy, "all_proxy": fallback_proxy})

    exceptions = re.search(
        r"ExceptionsList\s*:\s*<array>\s*\{(?P<body>.*?)^\s*\}",
        output,
        re.MULTILINE | re.DOTALL,
    )
    if exceptions:
        values = re.findall(r"^\s*\d+\s*:\s*(.*?)\s*$", exceptions.group("body"), re.MULTILINE)
        if values:
            no_proxy = ",".join(values)
            proxies.update({"NO_PROXY": no_proxy, "no_proxy": no_proxy})
    return proxies


def apply_system_proxy_fallback(env: dict[str, str] | None = None) -> str:
    """Use the active macOS system proxy only when no explicit proxy env exists."""

    target = os.environ if env is None else env
    if any(target.get(name) for name in PROXY_ENV_NAMES):
        return "environment"
    if sys.platform != "darwin":
        return "none"
    try:
        proc = subprocess.run(
            ["scutil", "--proxy"],
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "none"
    if proc.returncode != 0:
        return "none"
    proxies = parse_macos_system_proxy(proc.stdout or "")
    if not proxies:
        return "none"
    target.update(proxies)
    return "macos-system"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, value: str) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(value, encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def finalize_cancelled_job(job_dir: Path, meta: dict[str, Any], returncode: int = 130) -> dict[str, Any]:
    result_path = job_dir / "result.md"
    text = result_path.read_text(encoding="utf-8") if result_path.exists() else ""
    atomic_write_text(result_path, text)
    atomic_write_text(
        job_dir / "result.json",
        json.dumps(
            {
                "job_id": meta["job_id"],
                "status": "cancelled",
                "returncode": returncode,
                "text": text.strip(),
                "parsed": None,
                "stderr_tail": "",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    meta["status"] = "cancelled"
    meta["returncode"] = returncode
    meta["cancelled_at"] = meta.get("cancelled_at") or utc_now()
    meta["finished_at"] = meta.get("finished_at") or utc_now()
    meta.pop("pid", None)
    save_meta(job_dir, meta)
    return meta


def trim_text(value: str, limit: int = DEFAULT_CONTEXT_LIMIT) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    head = limit // 2
    tail = limit - head
    return (
        value[:head]
        + "\n\n[... truncated by grok-companion; original chars="
        + str(len(value))
        + " ...]\n\n"
        + value[-tail:],
        True,
    )


def run_quiet(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {"ok": False, "returncode": 127, "stdout": "", "stderr": f"missing binary: {cmd[0]}"}
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "ok": False,
            "returncode": 124,
            "stdout": stdout,
            "stderr": stderr or f"timed out after {timeout}s",
        }
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def git_capture(args: list[str], cwd: Path, timeout: int = 45) -> str:
    result = run_quiet(["git", *args], cwd=cwd, timeout=timeout)
    out = result["stdout"].strip()
    err = result["stderr"].strip()
    if result["ok"]:
        return out
    return f"[git {' '.join(args)} failed: {err or result['returncode']}]"


def collect_untracked_patch(root: Path, context_limit: int) -> tuple[str, list[str]]:
    result = run_quiet(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root)
    if not result["ok"]:
        return f"[git ls-files for untracked files failed: {result['stderr'].strip() or result['returncode']}]", []

    relative_paths = [item for item in result["stdout"].split("\0") if item]
    sections: list[str] = []
    included: list[str] = []
    remaining = max(context_limit, 0)
    for relative in relative_paths:
        if remaining <= 0:
            break
        candidate = root / relative
        if candidate.is_symlink():
            continue
        path = candidate.resolve()
        if path == root or root not in path.parents or not path.is_file():
            continue
        included.append(relative)
        header = [f"diff --git a/{relative} b/{relative}", "new file mode", "--- /dev/null", f"+++ b/{relative}"]
        try:
            with path.open("rb") as handle:
                data = handle.read(remaining + 1)
        except OSError as exc:
            section = "\n".join([*header, f"Unreadable untracked file: {exc}"])
            sections.append(section)
            remaining -= len(section)
            continue
        file_truncated = len(data) > remaining
        data = data[:remaining]
        if b"\0" in data:
            section = "\n".join([*header, "Binary untracked file omitted."])
            sections.append(section)
            remaining -= len(section)
            continue
        text = data.decode("utf-8", errors="replace")
        added_lines = "\n".join("+" + line for line in text.splitlines())
        if file_truncated:
            added_lines += f"\n+[... untracked file truncated to remaining context budget ...]"
        section = "\n".join([*header, "@@ untracked file @@", added_lines])
        sections.append(section)
        remaining -= len(section)
    return "\n\n".join(sections), included


def collect_git_context(cwd: Path, base: str | None, context_limit: int) -> dict[str, Any]:
    inside = run_quiet(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd)
    if not inside["ok"] or inside["stdout"].strip() != "true":
        return {
            "is_git_repo": False,
            "cwd": str(cwd),
            "summary": "Not inside a git repository.",
            "diff": "",
            "truncated": False,
        }

    root = Path(git_capture(["rev-parse", "--show-toplevel"], cwd) or cwd).resolve()
    status = git_capture(["status", "--short"], root)
    branch = git_capture(["branch", "--show-current"], root)
    head = git_capture(["rev-parse", "--short", "HEAD"], root)

    if base:
        stat = git_capture(["diff", "--stat", f"{base}...HEAD"], root)
        name_status = git_capture(["diff", "--name-status", f"{base}...HEAD"], root)
        diff = git_capture(["diff", "--find-renames", f"{base}...HEAD"], root, timeout=120)
        target = f"{base}...HEAD"
    else:
        untracked_patch, untracked_files = collect_untracked_patch(root, context_limit)
        stat_parts = [
            "Unstaged diff:",
            git_capture(["diff", "--stat"], root),
            "",
            "Staged diff:",
            git_capture(["diff", "--cached", "--stat"], root),
        ]
        diff_parts = [
            "## Unstaged diff",
            git_capture(["diff", "--find-renames"], root, timeout=120),
            "",
            "## Staged diff",
            git_capture(["diff", "--cached", "--find-renames"], root, timeout=120),
            "",
            "## Untracked files",
            untracked_patch,
        ]
        stat = "\n".join(stat_parts).strip()
        tracked_name_status = git_capture(["diff", "--name-status"], root) + "\n" + git_capture(["diff", "--cached", "--name-status"], root)
        untracked_name_status = "\n".join(f"??\t{path}" for path in untracked_files)
        name_status = tracked_name_status + "\n" + untracked_name_status
        diff = "\n".join(diff_parts).strip()
        target = "working tree + index"

    trimmed_diff, truncated = trim_text(diff, context_limit)
    return {
        "is_git_repo": True,
        "cwd": str(root),
        "branch": branch,
        "head": head,
        "target": target,
        "status_short": status,
        "diff_stat": stat,
        "name_status": name_status.strip(),
        "diff": trimmed_diff,
        "truncated": truncated,
        "context_limit": context_limit,
    }


def markdown_block(title: str, body: str) -> str:
    body = body.strip()
    if not body:
        body = "(empty)"
    return f"## {title}\n\n{body}\n"


def build_prompt(mode: str, task: str, args: argparse.Namespace, git_context: dict[str, Any] | None) -> str:
    shared = textwrap.dedent(
        f"""
        You are Grok acting as a complete external AI collaborator for a host agent (Codex or compatible).
        The host is a forwarder/coordinator. You own the Grok-side investigation, reasoning, and result quality.
        Use the full local Grok tool surface available in this session; do not wait for the host to re-paste missing files.

        Work mode: {mode}
        Current date: {dt.date.today().isoformat()}

        Rules:
        - Be concrete, critical, and useful. Prefer thorough evidence over brevity when the task is non-trivial.
        - Do not claim you changed files unless you actually did through tools.
        - If evidence is missing, retrieve it with tools when possible; otherwise say exactly what is missing.
        - For code review modes, present findings first and keep residual risk explicit.
        - Preserve Chinese if the user task is Chinese; otherwise answer in the task language.
        """
    ).strip()

    sections = [shared, markdown_block("Task", task)]

    if git_context:
        git_json = json.dumps(
            {k: v for k, v in git_context.items() if k != "diff"},
            ensure_ascii=False,
            indent=2,
        )
        sections.append(markdown_block("Repository Context", f"```json\n{git_json}\n```"))
        if git_context.get("diff"):
            sections.append(markdown_block("Diff", f"```diff\n{git_context['diff']}\n```"))
        if git_context.get("truncated"):
            sections.append(
                markdown_block(
                    "Context Completeness",
                    textwrap.dedent(
                        """
                        The embedded git context was truncated to the companion context budget.
                        Treat it as a partial packet, not the whole truth.
                        Use read-only tools (git status/diff/show/log, file reads, tests when allowed by the mode)
                        to inspect the rest of the target before finalizing conclusions.
                        Do not invent paths or hunks that you did not observe.
                        """
                    ).strip(),
                )
            )
        else:
            sections.append(
                markdown_block(
                    "Context Completeness",
                    "Use the embedded repository context as primary evidence. Still open nearby files with tools when a finding needs surrounding code.",
                )
            )

    if mode == "review":
        sections.append(
            markdown_block(
                "Review Contract",
                textwrap.dedent(
                    """
                    Run a thorough read-only code review. Do not propose broad rewrites unless needed for a concrete risk.

                    Return only the JSON object required by the supplied review schema.
                    Order findings by severity. Include precise file and line evidence when available.
                    Use an empty findings array and verdict "approve" when no actionable issue exists.
                    Do not under-report material issues to stay short; structured output is a format constraint, not a severity budget.

                    Prioritize bugs, regressions, data loss, auth/security, concurrency, deploy/runtime breakage, and missing tests.
                    """
                ),
            )
        )
    elif mode == "adversarial-review":
        sections.append(
            markdown_block(
                "Adversarial Review Contract",
                textwrap.dedent(
                    """
                    Challenge the implementation direction and assumptions, not only local bugs.
                    Look for hidden coupling, bad abstractions, risky defaults, migration hazards,
                    operational blind spots, rollback failure, and simpler alternatives.
                    Keep it read-only, specific, and complete enough that the host can decide without redoing the investigation.
                    """
                ),
            )
        )
    elif mode == "consult":
        sections.append(
            markdown_block(
                "Consult Contract",
                "Give a second opinion the host can use immediately. State your recommendation, tradeoffs, rejected alternatives, and what you would verify next.",
            )
        )
    elif mode == "research":
        sections.append(
            markdown_block(
                "Research Contract",
                "Produce a source-aware research brief. Separate confirmed facts, inferences, and recommendations. Include URLs when you used web/X tools. Prefer primary sources over summaries.",
            )
        )
    elif mode == "delegate":
        sections.append(
            markdown_block(
                "Delegate Contract",
                "Take the task as far as the full local Grok capability allows within the authorized write boundary. If you inspect or change files, summarize exact evidence and paths. If blocked, explain the blocker precisely.",
            )
        )
    elif mode == "ask":
        sections.append(
            markdown_block(
                "Ask Contract",
                "Answer directly and completely. Use tools whenever they improve factual accuracy; do not stay underpowered to save turns.",
            )
        )
    elif mode == "continue":
        sections.append(
            markdown_block(
                "Continue Contract",
                "Continue the resumed Grok session using its prior context. Address the new task directly and distinguish new evidence from earlier conclusions.",
            )
        )

    if getattr(args, "check", False) and mode in {"review", "adversarial-review"}:
        sections.append(
            markdown_block(
                "Self-Check Contract",
                "Before emitting the final JSON object, verify every conclusion against the task, repository context, diff, and output schema. Correct unsupported findings internally. Emit no verification prose outside the schema.",
            )
        )

    return "\n\n".join(sections).strip() + "\n"


def new_job_id(mode: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{mode}-{uuid.uuid4().hex[:8]}"


def load_meta(job_dir: Path) -> dict[str, Any]:
    return json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))


def save_meta(job_dir: Path, meta: dict[str, Any]) -> None:
    meta["updated_at"] = utc_now()
    atomic_write_text(job_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


def resolve_runtime_profile(args: argparse.Namespace, mode: str) -> None:
    profile = getattr(args, "profile", None) or DEFAULT_PROFILE
    defaults = PROFILE_DEFAULTS[profile]
    args.profile = profile
    if getattr(args, "max_turns", None) is None:
        args.max_turns = None if mode in UNBOUNDED_REVIEW_MODES else defaults["max_turns"]
    if getattr(args, "timeout", None) is None:
        args.timeout = defaults["timeout"]
    if getattr(args, "effort", None) is None and getattr(args, "reasoning_effort", None) is None:
        args.effort = defaults["effort"]
    if getattr(args, "check", None) is None:
        args.check = profile == "full" and mode in AUTO_CHECK_MODES


def resolved_check_strategy(mode: str, check: bool) -> str:
    if not check:
        return "off"
    if mode in {"review", "adversarial-review"}:
        return "prompt"
    return "native"


def create_job(mode: str, prompt: str, args: argparse.Namespace, git_context: dict[str, Any] | None = None) -> tuple[str, Path, dict[str, Any]]:
    jobs_dir = Path(args.jobs_dir).expanduser().resolve() if getattr(args, "jobs_dir", None) else default_jobs_dir()
    ensure_dir(jobs_dir)
    job_id = new_job_id(mode)
    job_dir = jobs_dir / job_id
    ensure_dir(job_dir)
    (job_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    if git_context is not None:
        atomic_write_text(job_dir / "context.json", json.dumps(git_context, ensure_ascii=False, indent=2) + "\n")
    meta = {
        "job_id": job_id,
        "version": VERSION,
        "mode": mode,
        "status": "created",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "cwd": str(Path.cwd().resolve()),
        "jobs_dir": str(jobs_dir),
        "job_dir": str(job_dir),
        "grok_bin": args.grok_bin,
        "profile": getattr(args, "profile", DEFAULT_PROFILE),
        "model": getattr(args, "model", None),
        "effort": getattr(args, "effort", None),
        "reasoning_effort": getattr(args, "reasoning_effort", None),
        "max_turns": getattr(args, "max_turns", DEFAULT_MAX_TURNS),
        "timeout": getattr(args, "timeout", DEFAULT_TIMEOUT),
        "tools": getattr(args, "tools", None),
        "disallowed_tools": getattr(args, "disallowed_tools", None),
        "disable_web_search": getattr(args, "disable_web_search", False),
        "check": getattr(args, "check", False),
        "check_strategy": resolved_check_strategy(mode, getattr(args, "check", False)),
        "best_of_n": getattr(args, "best_of_n", None),
        "session_id": getattr(args, "session_id", None),
        "format": getattr(args, "format", "md"),
        "prompt_path": str(job_dir / "prompt.md"),
        "result_path": str(job_dir / "result.md"),
        "raw_stdout_path": str(job_dir / "raw.stdout"),
        "raw_stderr_path": str(job_dir / "raw.stderr"),
    }
    save_meta(job_dir, meta)
    return job_id, job_dir, meta


def grok_command(meta: dict[str, Any]) -> list[str]:
    cmd = [
        meta.get("grok_bin") or "grok",
        "--prompt-file",
        meta["prompt_path"],
        "--output-format",
        "json",
    ]
    if meta.get("max_turns") is not None:
        cmd.extend(["--max-turns", str(meta["max_turns"])])
    cmd.extend(["--no-auto-update", "--always-approve"])
    if meta.get("model"):
        cmd.extend(["--model", meta["model"]])
    if meta.get("effort"):
        cmd.extend(["--effort", meta["effort"]])
    if meta.get("reasoning_effort"):
        cmd.extend(["--reasoning-effort", meta["reasoning_effort"]])
    if meta.get("best_of_n"):
        cmd.extend(["--best-of-n", str(meta["best_of_n"])])
    if meta.get("session_id"):
        cmd.extend(["--resume", meta["session_id"]])
    if meta.get("mode") in {"review", "adversarial-review"}:
        try:
            schema = REVIEW_SCHEMA_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReviewSchemaError(f"review schema unavailable: {REVIEW_SCHEMA_PATH}: {exc}") from exc
        cmd.extend(["--json-schema", schema])
    if meta.get("tools") is not None:
        cmd.extend(["--tools", meta["tools"]])
    if meta.get("disallowed_tools"):
        cmd.extend(["--disallowed-tools", meta["disallowed_tools"]])
    if meta.get("disable_web_search"):
        cmd.append("--disable-web-search")
    if meta.get("check_strategy") == "native":
        cmd.append("--check")
    return cmd


def extract_text(stdout: str) -> tuple[str, Any]:
    raw = stdout.strip()
    if not raw:
        return "", None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None
    if isinstance(parsed, dict):
        for key in ("text", "message", "content", "output"):
            value = parsed.get(key)
            if isinstance(value, str):
                return value.strip(), parsed
        return json.dumps(parsed, ensure_ascii=False, indent=2), parsed
    return str(parsed), parsed


def extract_session_id(parsed: Any) -> str | None:
    if not isinstance(parsed, dict):
        return None
    for key in ("sessionId", "session_id"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_review(parsed: Any) -> dict[str, Any] | None:
    candidates: list[Any] = []
    if isinstance(parsed, dict):
        candidates.append(parsed.get("structuredOutput"))
        candidates.append(parsed.get("structured_output"))
        for key in ("text", "content", "output"):
            value = parsed.get(key)
            if isinstance(value, str):
                try:
                    candidates.append(json.loads(value))
                except json.JSONDecodeError:
                    pass
    candidates.append(parsed)
    required = {"verdict", "summary", "findings", "next_steps"}
    for candidate in candidates:
        if isinstance(candidate, dict) and required.issubset(candidate):
            if candidate.get("verdict") not in {"approve", "needs-attention"}:
                continue
            if not isinstance(candidate.get("summary"), str) or not candidate["summary"].strip():
                continue
            if not isinstance(candidate.get("findings"), list) or not isinstance(candidate.get("next_steps"), list):
                continue
            if not all(isinstance(step, str) and step.strip() for step in candidate["next_steps"]):
                continue
            if not all(valid_review_finding(finding) for finding in candidate["findings"]):
                continue
            return candidate
    return None


def valid_review_finding(finding: Any) -> bool:
    if not isinstance(finding, dict):
        return False
    required = {"severity", "title", "body", "file", "line_start", "line_end", "confidence", "recommendation"}
    if set(finding) != required:
        return False
    if finding["severity"] not in {"critical", "high", "medium", "low"}:
        return False
    if not isinstance(finding["title"], str) or not finding["title"].strip():
        return False
    if not isinstance(finding["body"], str) or not finding["body"].strip():
        return False
    if not isinstance(finding["file"], str) or not isinstance(finding["recommendation"], str):
        return False
    for key in ("line_start", "line_end"):
        value = finding[key]
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            return False
    if finding["line_start"] and finding["line_end"] and finding["line_end"] < finding["line_start"]:
        return False
    confidence = finding["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        return False
    return True


def render_review_markdown(review: dict[str, Any]) -> str:
    lines = ["# Grok Review", "", f"**Verdict:** {review['verdict']}", "", str(review["summary"]).strip()]
    findings = review.get("findings") or []
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("No actionable findings.")
    for index, finding in enumerate(findings, 1):
        severity = str(finding.get("severity") or "unknown").upper()
        lines.append(f"### {index}. [{severity}] {finding.get('title') or 'Untitled finding'}")
        location = str(finding.get("file") or "").strip()
        line_start = finding.get("line_start")
        line_end = finding.get("line_end")
        if location:
            if line_start:
                location += f":{line_start}"
                if line_end and line_end != line_start:
                    location += f"-{line_end}"
            lines.extend(["", f"**Location:** `{location}`"])
        lines.extend(
            [
                "",
                str(finding.get("body") or "").strip(),
                "",
                f"**Confidence:** {finding.get('confidence', '')}",
                "",
                f"**Recommendation:** {str(finding.get('recommendation') or '').strip()}",
                "",
            ]
        )
    lines.extend(["## Next Steps", ""])
    next_steps = review.get("next_steps") or []
    if next_steps:
        lines.extend(f"- {step}" for step in next_steps)
    else:
        lines.append("- None.")
    return "\n".join(lines).strip() + "\n"


def finalize_runtime_failure(job_dir: Path, meta: dict[str, Any], message: str, returncode: int) -> int:
    (job_dir / "raw.stderr").write_text(message + "\n", encoding="utf-8")
    atomic_write_text(job_dir / "result.md", "")
    latest_meta = load_meta(job_dir)
    status = "cancelled" if latest_meta.get("status") in {"cancel_requested", "cancelled"} else "failed"
    atomic_write_text(
        job_dir / "result.json",
        json.dumps(
            {
                "job_id": meta["job_id"],
                "status": status,
                "returncode": returncode,
                "text": "",
                "parsed": None,
                "session_id": None,
                "review": None,
                "contract_error": message if returncode == 78 else None,
                "stderr_tail": message,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    latest_meta["status"] = status
    latest_meta["returncode"] = returncode
    latest_meta["error"] = message
    latest_meta["finished_at"] = utc_now()
    latest_meta.pop("pid", None)
    save_meta(job_dir, latest_meta)
    return returncode


def run_job(job_dir: Path) -> int:
    meta = load_meta(job_dir)
    if meta.get("status") == "cancel_requested":
        finalize_cancelled_job(job_dir, meta)
        return 130
    meta["status"] = "running"
    meta["pid"] = os.getpid()
    meta["started_at"] = utc_now()
    save_meta(job_dir, meta)

    try:
        cmd = grok_command(meta)
        meta["command"] = cmd
        save_meta(job_dir, meta)
        proc = subprocess.run(
            cmd,
            cwd=meta.get("cwd") or None,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=int(meta.get("timeout") or DEFAULT_TIMEOUT),
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        (job_dir / "raw.stdout").write_text(stdout, encoding="utf-8")
        (job_dir / "raw.stderr").write_text(stderr, encoding="utf-8")
        text, parsed = extract_text(stdout)
        session_id = extract_session_id(parsed)
        review = extract_review(parsed) if meta.get("mode") in {"review", "adversarial-review"} else None
        contract_error = None
        if meta.get("mode") in {"review", "adversarial-review"}:
            if review is None:
                contract_error = "Grok review output did not match the required structured review contract"
            else:
                text = render_review_markdown(review)
        atomic_write_text(job_dir / "result.md", text.strip() + ("\n" if text.strip() else ""))
        latest_meta = load_meta(job_dir)
        if latest_meta.get("status") in {"cancel_requested", "cancelled"}:
            status = "cancelled"
        elif proc.returncode == 0 and contract_error is None:
            status = "complete"
        else:
            status = "failed"
        effective_returncode = proc.returncode if proc.returncode != 0 else (2 if contract_error else 0)
        result_json = {
            "job_id": meta["job_id"],
            "status": status,
            "returncode": effective_returncode,
            "grok_returncode": proc.returncode,
            "text": text,
            "parsed": parsed,
            "session_id": session_id,
            "review": review,
            "contract_error": contract_error,
            "stderr_tail": stderr[-4000:],
        }
        atomic_write_text(job_dir / "result.json", json.dumps(result_json, ensure_ascii=False, indent=2) + "\n")
        latest_meta["status"] = status
        latest_meta["returncode"] = effective_returncode
        latest_meta["grok_returncode"] = proc.returncode
        latest_meta["finished_at"] = utc_now()
        if session_id:
            latest_meta["result_session_id"] = session_id
        if contract_error:
            latest_meta["error"] = contract_error
        latest_meta.pop("pid", None)
        save_meta(job_dir, latest_meta)
        return effective_returncode
    except ReviewSchemaError as exc:
        return finalize_runtime_failure(job_dir, meta, str(exc), 78)
    except FileNotFoundError:
        return finalize_runtime_failure(job_dir, meta, f"grok binary not found: {meta.get('grok_bin') or 'grok'}", 127)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        (job_dir / "raw.stdout").write_text(stdout, encoding="utf-8")
        (job_dir / "raw.stderr").write_text(stderr + f"\nTimed out after {meta.get('timeout')}s\n", encoding="utf-8")
        text, parsed = extract_text(stdout)
        session_id = extract_session_id(parsed)
        atomic_write_text(job_dir / "result.md", text.strip() + ("\n" if text.strip() else ""))
        latest_meta = load_meta(job_dir)
        status = "cancelled" if latest_meta.get("status") in {"cancel_requested", "cancelled"} else "timeout"
        latest_meta["status"] = status
        latest_meta["returncode"] = 124
        latest_meta["finished_at"] = utc_now()
        if session_id:
            latest_meta["result_session_id"] = session_id
        latest_meta.pop("pid", None)
        save_meta(job_dir, latest_meta)
        atomic_write_text(
            job_dir / "result.json",
            json.dumps(
                {
                    "job_id": meta["job_id"],
                    "status": status,
                    "returncode": 124,
                    "text": text,
                    "parsed": parsed,
                    "session_id": session_id,
                    "stderr_tail": stderr[-4000:],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        return 124


def start_background(job_dir: Path) -> int:
    stdout_path = job_dir / "runner.stdout"
    stderr_path = job_dir / "runner.stderr"
    cmd = [sys.executable, str(Path(__file__).resolve()), "_run-job", str(job_dir)]
    meta = load_meta(job_dir)
    meta["status"] = "starting"
    meta["runner_command"] = cmd
    save_meta(job_dir, meta)
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
    meta = load_meta(job_dir)
    if meta.get("status") in {"created", "starting", "running"}:
        meta["status"] = "running"
        meta["pid"] = proc.pid
    save_meta(job_dir, meta)
    return proc.pid


def resolve_job(jobs_dir: Path, job_id: str | None) -> Path:
    ensure_dir(jobs_dir)
    jobs_dir = jobs_dir.resolve()
    if job_id:
        if Path(job_id).name != job_id or job_id in {".", ".."} or "/" in job_id or "\\" in job_id:
            raise SystemExit(f"Invalid job id: {job_id}")
        direct = jobs_dir / job_id
        if direct.is_dir() and (direct / "meta.json").exists():
            return direct
        matches = sorted(
            path
            for path in jobs_dir.iterdir()
            if path.is_dir() and path.name.startswith(job_id) and (path / "meta.json").exists()
        )
        if len(matches) == 1:
            return matches[0]
        raise SystemExit(f"Job not found or ambiguous: {job_id}")
    jobs = sorted([p for p in jobs_dir.iterdir() if (p / "meta.json").exists()])
    if not jobs:
        raise SystemExit(f"No jobs found under {jobs_dir}")
    return jobs[-1]


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_running(pid: int) -> bool:
    if os.name == "nt":
        result = run_quiet(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], timeout=3)
        return result["ok"] and f'"{pid}"' in result["stdout"]
    result = run_quiet(["ps", "-o", "stat=", "-p", str(pid)], timeout=3)
    if result["ok"]:
        state = result["stdout"].strip()
        return bool(state) and not state.startswith("Z")
    return pid_alive(pid)


def wait_for_process_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_running(pid):
            return True
        time.sleep(0.05)
    return not process_running(pid)


def terminate_process_tree(pid: int) -> None:
    if os.name == "nt":
        proc = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise ProcessLookupError(proc.stderr.strip() or proc.stdout.strip() or f"taskkill failed for pid {pid}")
        if not wait_for_process_exit(pid, 2.0):
            raise RuntimeError(f"process tree still running after taskkill: {pid}")
        return
    if hasattr(os, "killpg"):
        os.killpg(pid, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGTERM)
    if wait_for_process_exit(pid, 2.0):
        return
    if hasattr(os, "killpg"):
        os.killpg(pid, signal.SIGKILL)
    else:
        os.kill(pid, signal.SIGKILL)
    if not wait_for_process_exit(pid, 2.0):
        raise RuntimeError(f"process tree still running after SIGKILL: {pid}")


def command_setup(args: argparse.Namespace) -> int:
    grok_path = which(args.grok_bin) if not os.path.isabs(args.grok_bin) else args.grok_bin
    report: dict[str, Any] = {
        "status": "ok",
        "version": VERSION,
        "grok_bin": args.grok_bin,
        "grok_path": grok_path,
        "jobs_dir": str(Path(args.jobs_dir).expanduser().resolve() if args.jobs_dir else default_jobs_dir()),
        "superx_path": which("superx"),
        "checks": {},
    }
    if not grok_path:
        report["status"] = "degraded"
        report["checks"]["grok"] = {"ok": False, "error": "grok binary not found"}
    else:
        report["checks"]["grok_version"] = run_quiet([args.grok_bin, "version"], timeout=args.timeout)
        report["checks"]["grok_models"] = run_quiet([args.grok_bin, "models"], timeout=args.timeout)

    if args.probe_superx:
        if which("superx"):
            report["checks"]["superx_doctor"] = run_quiet(["superx", "doctor", "--format", "json", "--no-update-check"], timeout=args.timeout)
        else:
            report["checks"]["superx_doctor"] = {"ok": False, "returncode": 127, "stdout": "", "stderr": "superx not found"}

    if any(isinstance(check, dict) and not check.get("ok", False) for check in report["checks"].values()):
        report["status"] = "degraded"

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"grok-companion setup: {report['status']}")
        print(f"grok: {grok_path or 'missing'}")
        print(f"jobs: {report['jobs_dir']}")
        if report.get("superx_path"):
            print(f"superx: {report['superx_path']}")
        for name, check in report["checks"].items():
            ok = check.get("ok") if isinstance(check, dict) else False
            print(f"{name}: {'ok' if ok else 'failed'}")
            if isinstance(check, dict) and check.get("stderr"):
                print(textwrap.indent(check["stderr"].strip()[-600:], "  "))
    return 0 if report["status"] == "ok" else 1


def execute_mode(args: argparse.Namespace, mode: str) -> int:
    resolve_runtime_profile(args, mode)
    task_parts = args.task[1:] if args.task and args.task[0] == "--" else args.task
    task = " ".join(task_parts).strip()
    if not task:
        raise SystemExit(f"{mode} requires a task/prompt")
    git_context = None
    if mode in {"review", "adversarial-review"} or getattr(args, "include_git_context", False):
        git_context = collect_git_context(Path.cwd().resolve(), getattr(args, "base", None), getattr(args, "context_limit", DEFAULT_CONTEXT_LIMIT))
    prompt = build_prompt(mode, task, args, git_context)
    job_id, job_dir, _meta = create_job(mode, prompt, args, git_context)
    if getattr(args, "background", False):
        pid = start_background(job_dir)
        print(json.dumps({"job_id": job_id, "status": "running", "pid": pid, "job_dir": str(job_dir)}, ensure_ascii=False, indent=2))
        return 0
    code = run_job(job_dir)
    result_path = job_dir / "result.md"
    text = result_path.read_text(encoding="utf-8") if result_path.exists() else ""
    if args.format == "json":
        result_json_path = job_dir / "result.json"
        payload = json.loads(result_json_path.read_text(encoding="utf-8")) if result_json_path.exists() else {"text": text}
        payload["job_dir"] = str(job_dir)
        payload["job_id"] = job_id
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.path_only:
        print(result_path)
    else:
        if text:
            print(text)
        else:
            stderr_path = job_dir / "raw.stderr"
            if stderr_path.exists():
                print(stderr_path.read_text(encoding="utf-8")[-2000:], file=sys.stderr)
    return code


def refresh_job_meta(job_dir: Path) -> dict[str, Any]:
    meta = load_meta(job_dir)
    pid = meta.get("pid")
    if meta.get("status") in {"running", "cancel_requested"} and pid and not process_running(int(pid)):
        meta = load_meta(job_dir)
        if meta.get("status") == "cancel_requested":
            return finalize_cancelled_job(job_dir, meta)
        result = load_result_payload(job_dir)
        result_status = result.get("status") if result else None
        if result_status in TERMINAL_STATUSES:
            meta["status"] = result_status
            meta["warning"] = "recovered terminal status from result.json after runner exited before final metadata update"
            meta["returncode"] = result.get("returncode")
            meta["finished_at"] = meta.get("finished_at") or utc_now()
        else:
            meta["status"] = "unknown"
            meta["warning"] = "pid is no longer alive and no terminal result was recorded"
            meta["finished_at"] = meta.get("finished_at") or utc_now()
        meta.pop("pid", None)
        save_meta(job_dir, meta)
    return meta


def load_result_payload(job_dir: Path) -> dict[str, Any] | None:
    result_path = job_dir / "result.json"
    if not result_path.exists():
        return None
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["job_dir"] = str(job_dir)
    return payload


def parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def read_tail(path: Path, limit: int) -> str:
    if limit <= 0 or not path.exists():
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max(4096, limit * 4)))
            return handle.read().decode("utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_monitor_output(output: Path) -> Path:
    resolved = output.expanduser().resolve()
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve()
    allowed_roots = (Path.cwd().resolve(), codex_home / "visualizations")
    if not any(path_is_within(resolved, root) for root in allowed_roots):
        roots = " or ".join(str(root) for root in allowed_roots)
        raise SystemExit(f"Monitor output must be inside {roots}")
    if resolved.suffix.lower() != ".html":
        raise SystemExit("Monitor output must use an .html extension")
    return resolved


def build_monitor_snapshot(job_dir: Path, tail_chars: int = 4000) -> dict[str, Any]:
    tail_chars = max(0, min(tail_chars, 20000))
    meta = refresh_job_meta(job_dir)
    status = str(meta.get("status") or "unknown")
    terminal = status in TERMINAL_STATUSES
    started = parse_timestamp(meta.get("started_at") or meta.get("created_at"))
    finished = parse_timestamp(meta.get("finished_at")) if terminal else None
    if terminal and finished is None:
        meta["finished_at"] = meta.get("updated_at") or utc_now()
        save_meta(job_dir, meta)
        finished = parse_timestamp(meta["finished_at"])
    now = dt.datetime.now(dt.timezone.utc)
    elapsed = max(0.0, ((finished or now) - started).total_seconds()) if started else 0.0
    timeout = int(meta.get("timeout") or DEFAULT_TIMEOUT)
    try:
        result = load_result_payload(job_dir) if terminal else None
    except (OSError, json.JSONDecodeError):
        result = None
    result_text = str(result.get("text") or "") if result else ""
    session_id = meta.get("result_session_id") or (result.get("session_id") if result else None) or meta.get("session_id")
    pid = meta.get("pid")
    alive = process_running(int(pid)) if isinstance(pid, int) else False
    actions = ["refresh"]
    if terminal:
        if result is not None:
            actions.append("result")
        if session_id:
            actions.append("continue")
    else:
        actions.extend(["wait", "cancel"])
    return {
        "version": VERSION,
        "job_id": meta.get("job_id"),
        "status": status,
        "terminal": terminal,
        "job_ok": (result.get("status") == "complete" if result else status == "complete") if terminal else None,
        "mode": meta.get("mode"),
        "profile": meta.get("profile") or DEFAULT_PROFILE,
        "max_turns": meta.get("max_turns") if "max_turns" in meta else DEFAULT_MAX_TURNS,
        "timeout": timeout,
        "remaining_seconds": round(max(0.0, timeout - elapsed), 3) if not terminal else None,
        "check": bool(meta.get("check")),
        "check_strategy": meta.get("check_strategy") or "off",
        "elapsed_seconds": round(elapsed, 3),
        "created_at": meta.get("created_at"),
        "started_at": meta.get("started_at"),
        "updated_at": meta.get("updated_at"),
        "finished_at": meta.get("finished_at"),
        "last_activity_at": meta.get("updated_at"),
        "pid": pid,
        "alive": alive,
        "session_id": session_id,
        "job_dir": str(job_dir),
        "stream_available": False,
        "stdout_tail": read_tail(job_dir / "raw.stdout", tail_chars),
        "stderr_tail": read_tail(job_dir / "raw.stderr", tail_chars),
        "runner_stderr_tail": read_tail(job_dir / "runner.stderr", tail_chars),
        "result_preview": (result_text[:797] + "...") if len(result_text) > 800 else (result_text or None),
        "actions": actions,
    }


def render_monitor_html(snapshot: dict[str, Any]) -> str:
    try:
        template = MONITOR_TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Monitor template unavailable: {MONITOR_TEMPLATE_PATH}: {exc}") from exc
    payload = json.dumps(snapshot, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    marker = "__GROK_MONITOR_JSON__"
    if marker not in template:
        raise SystemExit(f"Monitor template marker missing: {marker}")
    return template.replace(marker, payload)


def resolve_resume_session(jobs_dir: Path, job_id: str | None, session_id: str | None) -> str:
    if session_id:
        return session_id
    if job_id:
        jobs = [resolve_job(jobs_dir, job_id)]
    else:
        ensure_dir(jobs_dir)
        jobs = sorted([path for path in jobs_dir.iterdir() if (path / "meta.json").exists()], reverse=True)
    for job_dir in jobs:
        meta = load_meta(job_dir)
        candidate = meta.get("result_session_id")
        if not candidate:
            result = load_result_payload(job_dir)
            candidate = result.get("session_id") if result else None
        if isinstance(candidate, str) and candidate:
            return candidate
    target = job_id or "recent Grok Companion jobs"
    raise SystemExit(f"No resumable Grok session found for {target}")


def execute_continue(args: argparse.Namespace) -> int:
    jobs_dir = Path(args.jobs_dir).expanduser().resolve() if args.jobs_dir else default_jobs_dir()
    args.session_id = resolve_resume_session(jobs_dir, args.job_id, args.session_id)
    return execute_mode(args, "continue")


def command_sessions(args: argparse.Namespace) -> int:
    cmd = [args.grok_bin, "sessions", "search" if args.query else "list"]
    if args.query:
        cmd.append(args.query)
    cmd.extend(["--limit", str(args.limit)])
    result = run_quiet(cmd, cwd=Path.cwd().resolve(), timeout=args.timeout)
    session_ids = []
    for line in result["stdout"].splitlines():
        first = line.strip().split(maxsplit=1)[0] if line.strip() else ""
        if first == "SESSION" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,}", first):
            continue
        session_ids.append(first)
    payload = {
        "status": "ok" if result["ok"] else "failed",
        "query": args.query,
        "limit": args.limit,
        "session_ids": session_ids,
        "text": result["stdout"].strip(),
        "stderr": result["stderr"].strip(),
        "returncode": result["returncode"],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload["text"]:
        print(payload["text"])
    elif payload["stderr"]:
        print(payload["stderr"], file=sys.stderr)
    return 0 if result["ok"] else int(result["returncode"] or 1)


def command_status(args: argparse.Namespace) -> int:
    jobs_dir = Path(args.jobs_dir).expanduser().resolve() if args.jobs_dir else default_jobs_dir()
    ensure_dir(jobs_dir)
    if args.detail == "monitor":
        job_dir = resolve_job(jobs_dir, args.job_id)
        snapshot = build_monitor_snapshot(job_dir, args.tail_chars)
        payload = {"detail": "monitor", "snapshot": snapshot}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"{snapshot['job_id']}  {snapshot['status']}  elapsed={snapshot['elapsed_seconds']}s")
            turns = snapshot["max_turns"] if snapshot["max_turns"] is not None else "unlimited"
            print(f"  profile={snapshot['profile']}  turns={turns}  runtime={snapshot['timeout']}s")
            print(f"  alive={str(snapshot['alive']).lower()}  session={snapshot['session_id'] or '-'}")
        return 0
    jobs = sorted([p for p in jobs_dir.iterdir() if (p / "meta.json").exists()])
    if args.job_id:
        jobs = [resolve_job(jobs_dir, args.job_id)]
    else:
        jobs = jobs[-args.limit :]
    rows = []
    for job in jobs:
        rows.append(refresh_job_meta(job))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        if not rows:
            print(f"No jobs under {jobs_dir}")
            return 0
        for meta in rows:
            print(f"{meta['job_id']}  {meta.get('status')}  {meta.get('mode')}  {meta.get('updated_at')}")
            print(f"  {meta.get('job_dir')}")
    return 0


def command_monitor(args: argparse.Namespace) -> int:
    jobs_dir = Path(args.jobs_dir).expanduser().resolve() if args.jobs_dir else default_jobs_dir()
    job_dir = resolve_job(jobs_dir, args.job_id)
    snapshot = build_monitor_snapshot(job_dir, args.tail_chars)
    output = validate_monitor_output(Path(args.output))
    ensure_dir(output.parent)
    atomic_write_text(output, render_monitor_html(snapshot))
    payload = {"snapshot": snapshot, "visualization_path": str(output)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(output)
    return 0


def print_watch_snapshot(snapshot: dict[str, Any]) -> None:
    turns = snapshot["max_turns"] if snapshot["max_turns"] is not None else "unlimited"
    print(f"Grok Job  {snapshot['job_id']}")
    print(f"status    {snapshot['status']}  elapsed {snapshot['elapsed_seconds']}s  alive {str(snapshot['alive']).lower()}")
    print(f"runtime   {snapshot['profile']}  {turns} turns  {snapshot['timeout']}s  check {snapshot['check_strategy']}")
    print(f"session   {snapshot['session_id'] or '-'}")
    preview = snapshot.get("result_preview") or snapshot.get("runner_stderr_tail") or "Process status only; Grok output is stored when the job exits."
    print("\n" + str(preview).strip())


def command_watch(args: argparse.Namespace) -> int:
    if args.interval <= 0:
        raise SystemExit("Watch interval must be greater than zero")
    jobs_dir = Path(args.jobs_dir).expanduser().resolve() if args.jobs_dir else default_jobs_dir()
    job_dir = resolve_job(jobs_dir, args.job_id)
    try:
        while True:
            snapshot = build_monitor_snapshot(job_dir, args.tail_chars)
            if args.json:
                print(json.dumps(snapshot, ensure_ascii=False), flush=True)
            else:
                if sys.stdout.isatty():
                    print("\033[2J\033[H", end="")
                print_watch_snapshot(snapshot)
            if args.once or snapshot["terminal"]:
                return 0 if snapshot["job_ok"] is not False else 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped watching; the Grok job is still running.", file=sys.stderr)
        return 130


def command_wait(args: argparse.Namespace) -> int:
    jobs_dir = Path(args.jobs_dir).expanduser().resolve() if args.jobs_dir else default_jobs_dir()
    job_dir = resolve_job(jobs_dir, args.job_id)
    started = time.monotonic()
    deadline = started + args.timeout
    meta = refresh_job_meta(job_dir)
    while meta.get("status") not in TERMINAL_STATUSES and time.monotonic() < deadline:
        time.sleep(args.poll_interval)
        meta = refresh_job_meta(job_dir)
    completed = meta.get("status") in TERMINAL_STATUSES
    job_ok = meta.get("status") == "complete" if completed else None
    payload = {
        "job_id": meta["job_id"],
        "status": meta.get("status"),
        "completed": completed,
        "job_ok": job_ok,
        "next_action": "read_result" if job_ok else ("inspect_failure" if completed else "wait_same_job"),
        "waited_seconds": round(time.monotonic() - started, 3),
        "job_dir": str(job_dir),
        "result": load_result_payload(job_dir) if completed else None,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['job_id']}  {payload['status']}  completed={str(completed).lower()}")
        if completed and payload["result"] and payload["result"].get("text"):
            print(payload["result"]["text"])
    if completed and not payload["job_ok"]:
        result_code = payload["result"].get("returncode") if payload["result"] else None
        return int(result_code) if isinstance(result_code, int) and result_code != 0 else 1
    return 0


def command_result(args: argparse.Namespace) -> int:
    jobs_dir = Path(args.jobs_dir).expanduser().resolve() if args.jobs_dir else default_jobs_dir()
    job_dir = resolve_job(jobs_dir, args.job_id)
    if args.json:
        payload = load_result_payload(job_dir)
        if payload is not None:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(load_meta(job_dir), ensure_ascii=False, indent=2))
        return 0
    result_path = job_dir / "result.md"
    if not result_path.exists():
        raise SystemExit(f"No result yet for {job_dir.name}")
    if args.path_only:
        print(result_path)
    else:
        print(result_path.read_text(encoding="utf-8"), end="")
    return 0


def command_cancel(args: argparse.Namespace) -> int:
    jobs_dir = Path(args.jobs_dir).expanduser().resolve() if args.jobs_dir else default_jobs_dir()
    job_dir = resolve_job(jobs_dir, args.job_id)
    meta = load_meta(job_dir)
    pid = meta.get("pid")
    if not pid:
        if meta.get("status") in {"created", "starting"}:
            meta["status"] = "cancel_requested"
            meta["cancel_requested_at"] = utc_now()
            save_meta(job_dir, meta)
            payload = {"job_id": meta["job_id"], "status": "cancel_requested", "cancelled": False}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"Cancellation requested for {meta['job_id']}")
            return 0
        payload = {
            "job_id": meta["job_id"],
            "status": meta.get("status"),
            "cancelled": False,
            "error": "job has no running pid",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Job {meta['job_id']} has no running pid; status={meta.get('status')}")
        return 1
    meta["status"] = "cancel_requested"
    meta["cancel_requested_at"] = utc_now()
    save_meta(job_dir, meta)
    try:
        terminate_process_tree(int(pid))
        latest_meta = load_meta(job_dir)
        finalize_cancelled_job(job_dir, latest_meta)
        payload = {"job_id": meta["job_id"], "status": "cancelled", "cancelled": True, "pid": int(pid)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Cancelled {meta['job_id']} (pid {pid})")
        return 0
    except ProcessLookupError:
        latest_meta = load_meta(job_dir)
        if latest_meta.get("status") in {"cancel_requested", "cancelled"}:
            finalize_cancelled_job(job_dir, latest_meta)
            payload = {"job_id": meta["job_id"], "status": "cancelled", "cancelled": True, "pid": int(pid)}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"Cancelled {meta['job_id']} (process already exited)")
            return 0
        if latest_meta.get("status") not in TERMINAL_STATUSES:
            latest_meta["status"] = "unknown"
            latest_meta["warning"] = "pid not found during cancel"
            latest_meta["finished_at"] = latest_meta.get("finished_at") or utc_now()
            latest_meta.pop("pid", None)
            save_meta(job_dir, latest_meta)
        payload = {
            "job_id": meta["job_id"],
            "status": latest_meta.get("status"),
            "cancelled": False,
            "error": "process already gone",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Process already gone for {meta['job_id']}")
        return 1
    except RuntimeError as exc:
        latest_meta = load_meta(job_dir)
        latest_meta["status"] = "cancel_requested"
        latest_meta["warning"] = str(exc)
        save_meta(job_dir, latest_meta)
        payload = {
            "job_id": meta["job_id"],
            "status": "cancel_requested",
            "cancelled": False,
            "error": str(exc),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(str(exc))
        return 1


def add_runtime_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--grok-bin", default=default_grok_bin(), help="Grok CLI binary (default: GROK_BIN, PATH, or a standard user install path)")
    parser.add_argument("--jobs-dir", help="Job artifact directory (default: repo/.grok-companion/jobs)")
    parser.add_argument("--model", help="Grok model id")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="Grok reasoning effort alias")
    parser.add_argument("--reasoning-effort", help="Explicit reasoning effort")
    parser.add_argument("--profile", choices=sorted(PROFILE_DEFAULTS), default=DEFAULT_PROFILE, help="Runtime profile (default: full)")
    parser.add_argument("--max-turns", type=int, help="Override the profile turn budget")
    parser.add_argument("--timeout", type=int, help="Override the profile job runtime in seconds")
    parser.add_argument("--tools", help="Comma-separated Grok tools allowlist")
    parser.add_argument("--disallowed-tools", help="Comma-separated Grok tools denylist")
    parser.add_argument("--disable-web-search", action="store_true")
    check_group = parser.add_mutually_exclusive_group()
    check_group.add_argument("--check", dest="check", action="store_true", help="Force Grok self-verification on")
    check_group.add_argument("--no-check", dest="check", action="store_false", help="Force Grok self-verification off")
    parser.set_defaults(check=None)
    parser.add_argument("--best-of-n", type=int, help="Use Grok best-of-N for the primary run")
    parser.add_argument("--session-id", help="Resume an existing Grok session id")
    parser.add_argument("--background", action="store_true", help="Start job and return immediately")
    parser.add_argument("--wait", action="store_true", help="Run foreground; kept for compatibility and readability")
    parser.add_argument("--format", choices=["md", "json"], default="md")
    parser.add_argument("--path-only", action="store_true", help="Print only result.md path after foreground completion")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grb",
        description="Grok Companion: a local Grok collaborator bridge for Codex and other agents.",
    )
    parser.add_argument("--version", action="version", version=f"grok-companion {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="Check Grok CLI, models, job directory, and optional superx")
    p_setup.add_argument("--grok-bin", default=default_grok_bin())
    p_setup.add_argument("--jobs-dir")
    p_setup.add_argument("--timeout", type=int, default=30)
    p_setup.add_argument("--probe-superx", action="store_true")
    p_setup.add_argument("--json", action="store_true")
    p_setup.set_defaults(func=command_setup)

    for name, help_text in [
        ("ask", "Ask Grok a direct question"),
        ("consult", "Ask Grok for a second opinion"),
        ("research", "Ask Grok for a research brief"),
        ("delegate", "Delegate a bounded task to Grok"),
    ]:
        p = sub.add_parser(name, help=help_text)
        add_runtime_flags(p)
        p.add_argument("--include-git-context", action="store_true", help="Include git status/diff context")
        p.add_argument("--base", help="Optional git base ref when including git context")
        p.add_argument("--context-limit", type=int, default=DEFAULT_CONTEXT_LIMIT)
        p.add_argument("task", nargs=argparse.REMAINDER)
        p.set_defaults(func=lambda args, mode=name: execute_mode(args, mode))

    for name, help_text in [
        ("review", "Read-only Grok code review"),
        ("adversarial-review", "Read-only Grok challenge review"),
    ]:
        p = sub.add_parser(name, help=help_text)
        add_runtime_flags(p)
        p.add_argument("--base", help="Review branch diff against base ref, e.g. main")
        p.add_argument("--context-limit", type=int, default=DEFAULT_CONTEXT_LIMIT)
        p.add_argument("task", nargs=argparse.REMAINDER)
        p.set_defaults(func=lambda args, mode=name: execute_mode(args, mode))

    p_continue = sub.add_parser("continue", help="Continue a prior Grok session from a companion job or session id")
    add_runtime_flags(p_continue)
    p_continue.add_argument("--job-id", help="Companion job whose returned Grok session should be resumed")
    p_continue.add_argument("--include-git-context", action="store_true", help="Include current git status/diff context")
    p_continue.add_argument("--base", help="Optional git base ref when including git context")
    p_continue.add_argument("--context-limit", type=int, default=DEFAULT_CONTEXT_LIMIT)
    p_continue.add_argument("task", nargs=argparse.REMAINDER)
    p_continue.set_defaults(func=execute_continue)

    p_sessions = sub.add_parser("sessions", help="List or search Grok CLI sessions")
    p_sessions.add_argument("query", nargs="?", help="Optional search query")
    p_sessions.add_argument("--grok-bin", default=default_grok_bin())
    p_sessions.add_argument("--limit", type=int, default=20)
    p_sessions.add_argument("--timeout", type=int, default=30)
    p_sessions.add_argument("--json", action="store_true")
    p_sessions.set_defaults(func=command_sessions)

    p_status = sub.add_parser("status", help="Show running and recent jobs")
    p_status.add_argument("job_id", nargs="?")
    p_status.add_argument("--jobs-dir")
    p_status.add_argument("--limit", type=int, default=10)
    p_status.add_argument("--detail", choices=["summary", "monitor"], default="summary")
    p_status.add_argument("--tail-chars", type=int, default=4000)
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=command_status)

    p_monitor = sub.add_parser("monitor", help="Render a snapshot of a Grok job as an inline visualization fragment")
    p_monitor.add_argument("job_id", nargs="?")
    p_monitor.add_argument("--jobs-dir")
    p_monitor.add_argument("--output", required=True)
    p_monitor.add_argument("--tail-chars", type=int, default=4000)
    p_monitor.add_argument("--json", action="store_true")
    p_monitor.set_defaults(func=command_monitor)

    p_watch = sub.add_parser("watch", help="Watch one Grok job in a user-opened terminal")
    p_watch.add_argument("job_id", nargs="?")
    p_watch.add_argument("--jobs-dir")
    p_watch.add_argument("--interval", type=float, default=2.0)
    p_watch.add_argument("--tail-chars", type=int, default=4000)
    p_watch.add_argument("--once", action="store_true")
    p_watch.add_argument("--json", action="store_true")
    p_watch.set_defaults(func=command_watch)

    p_wait = sub.add_parser("wait", help="Wait for a background job without repeated status polling")
    p_wait.add_argument("job_id", nargs="?")
    p_wait.add_argument("--jobs-dir")
    p_wait.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_WAIT_TIMEOUT,
        help="Maximum seconds to wait before returning (observation window only)",
    )
    p_wait.add_argument("--poll-interval", type=float, default=0.25)
    p_wait.add_argument("--json", action="store_true")
    p_wait.set_defaults(func=command_wait)

    p_result = sub.add_parser("result", help="Print a finished job result")
    p_result.add_argument("job_id", nargs="?")
    p_result.add_argument("--jobs-dir")
    p_result.add_argument("--json", action="store_true")
    p_result.add_argument("--path-only", action="store_true")
    p_result.set_defaults(func=command_result)

    p_cancel = sub.add_parser("cancel", help="Cancel a running background job")
    p_cancel.add_argument("job_id", nargs="?")
    p_cancel.add_argument("--jobs-dir")
    p_cancel.add_argument("--json", action="store_true")
    p_cancel.set_defaults(func=command_cancel)

    p_run = sub.add_parser("_run-job", help=argparse.SUPPRESS)
    p_run.add_argument("job_dir")
    p_run.set_defaults(func=lambda args: run_job(Path(args.job_dir).expanduser().resolve()))
    return parser


def main(argv: list[str] | None = None) -> int:
    apply_system_proxy_fallback()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
