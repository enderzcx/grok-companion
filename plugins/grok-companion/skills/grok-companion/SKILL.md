---
name: grok-companion
description: "Use when the user explicitly asks Codex to collaborate with Grok, or when an active host policy has pre-authorized automatic collaborator selection and selects Grok for a bounded task. Supports second opinions, review, adversarial review, research, bounded delegation, session continuation, and job management. Not for generic code review or web research without either activation path, exact X/Twitter retrieval or search (use superx), another named AI collaborator, or requests for a sidebar terminal."
license: MIT
compatibility: Requires local Grok CLI (`grok` or GROK_BIN), Python 3.9+, and a client that loads Agent Skills plus stdio MCP (Codex plugin install is the primary path).
metadata:
  short-description: Use Grok as a managed Codex collaborator
  sunny_skill_type: wrapper
  agent_plugins: "1.0.0"
---

# Grok Companion

Use the local `grok` CLI as an external Codex collaborator through native MCP tools and one durable job runtime.

## Before Calling

Read [references/routing.md](references/routing.md) when ownership is ambiguous. There are two activation paths:

1. The user explicitly requests Grok collaboration or is already managing a Grok Companion job.
2. An active host policy explicitly pre-authorizes automatic collaborator selection, the current task lead selects Grok, and the task satisfies that policy's bounded authority and acceptance rules.

The second path is opt-in host behavior. Do not infer it merely because work is difficult, non-trivial, cross-file, or benefits from review. When the policy-selected path is used, emit `🧭 route: <lead> -> Grok <role> | reason: <short reason>` before launching the job.

For exact X/Twitter URLs, posts, accounts, threads, articles, search, or X-native diagnostics, use `superx` instead.

## Call Path

Treat this plugin like a full Grok collaborator bridge (same product idea as `openai/codex-plugin-cc`, but for Grok): the host forwards a complete task; Grok keeps its full tool surface and reasoning budget. Do not starve Grok to fit one host turn.

1. Prefer visible `grok_*` MCP tools.
2. Pass the absolute current workspace as `cwd` on every call.
3. Give Grok the complete task and all relevant constraints in one launch. Prefer `profile=full` (default): model `grok-4.6`, no plugin-imposed turn cap, effort `xhigh`, job runtime `7200` seconds, and embedded git/diff budget `context_limit` default `256000` characters. Review, adversarial review, and research also self-check under full. Pass `effort=high` (or lower) only when you want a cheaper/faster turn.
4. Use `profile=quick` only for connectivity smoke, a deliberately small fixed-answer task, or an explicit user request. Ordinary quick tasks resolve to 16 turns, effort `xhigh`, and 900 seconds. Structured `review` / `adversarial-review` stay uncapped unless the caller explicitly supplies `max_turns`.
5. Do not add `max_turns` merely to fit the current host wait window. Default model is `grok-4.6`, which accepts `low|medium|high|xhigh`. Do not pass `effort=xhigh` or `max` on `grok-4.5`: live CLI rejects them with `use one of: high, medium, low`, so the runtime keeps effort `high`. Prefer tool-read over megabyte-scale `context_limit` when the diff is huge.
6. Read-only `review` / `adversarial-review` recover from explicit `reqwest` streaming transport failures twice by default inside the original job timeout. The first attempt owns a stable session; recovery resumes it with tools disabled and requests only the final structured result instead of re-running the review. Other modes default to no automatic transport retry so writes or external effects are never duplicated. Use explicit `transport_retries` only when that boundary is intentional. If Grok answers a review without inspecting anything (verdict `needs-attention` with zero findings, or one turn with no embedded diff), the job resumes the same session once with tools enabled; a review that is still unperformed ends as `job_ok: false` with `contract_error` "Grok did not perform the review" rather than a green result.
7. Launch tools return a background `job_id`.
8. Call `grok_wait` with a bounded observation window (default 180s). If it returns `completed: false`, it also returns `job_ok: null` and `next_action: wait_same_job`; call it again with the same `job_id`. Avoid tight `grok_status` polling.
9. When the user wants to see Grok working, call `grok_monitor` with the job and an absolute `.html` path in the current Codex visualization directory, then present that file as an inline visualization. Refreshing renders a new snapshot; it is not a live token stream.
10. Follow [references/result-handling.md](references/result-handling.md) when presenting or accepting results.
11. Use the bundled `scripts/grb.py` CLI only when MCP is unavailable or foreground execution is specifically required.

After a plugin upgrade, an already-open task may retain an older MCP process. Version 0.4.8 and later hand that process off to the highest installed `grb.py` under the same marketplace/plugin cache root when its pinned runtime was removed. Preserve any returned `runtime_handoff` receipt. Start a new task when refreshed Skill instructions or MCP schemas matter; missing old cache alone is no longer a reason to relaunch a Grok job blindly.

Explicit `max_turns`, job `timeout`, `context_limit`, `transport_retries`, and `check` values override the selected profile. The launch `timeout` is Grok's total job runtime across retries; the `grok_wait` timeout is only one observation window and never cancels the job.

`check` is a Companion self-verification intent, not a raw Grok CLI flag. Full-profile review, adversarial review, and research inject the self-check contract into the task prompt; never add Grok's removed `--check` option to a launch command.

Do not invent tools that are not visible in the current session.

When version or routing drift is suspected, use the installed bounded SOP interface from this skill directory:

```bash
python3 scripts/skill_registry.py list
python3 scripts/skill_registry.py read references/routing.md
python3 scripts/skill_registry.py validate
```

It exposes only `SKILL.md`, `references/`, `templates/`, and `evals/`; it refuses scripts, logs, assets, secrets, absolute paths, and dot-segment escapes.

## Tool Selection

- `grok_setup`: diagnose CLI, model access, jobs, and optional `superx`.
- `grok_ask`: direct Grok question.
- `grok_consult`: second opinion and tradeoff analysis.
- `grok_review`: structured, read-only code findings.
- `grok_adversarial_review`: structured challenge of architecture and assumptions.
- `grok_research`: source-aware general research.
- `grok_delegate`: bounded work authorized directly by the user or by an active host policy with an approved write boundary.
- `grok_continue`: continue by `session_id`, prior companion `job_id`, or the latest resumable companion job.
- `grok_sessions`: list or search Grok CLI sessions.
- `grok_status`: inspect jobs without waiting.
- `grok_monitor`: render a refreshable inline job snapshot with status, budget, session, result preview, and follow-up actions.
- `grok_wait`: perform one bounded wait; repeat with the same job until terminal.
- `grok_result`: read a stored result.
- `grok_cancel`: terminate a background job and its process tree.

## Safety

- Review modes are read-only contracts. Without `base`, they include unstaged, staged, and untracked text files within the context budget.
- Give Grok the complete task and all relevant repository context available for the decision. For follow-up questions on the same problem, use `grok_continue` so the existing Grok session context is preserved.
- Do not cancel or restart a running job merely because a bounded wait returned incomplete. Cancel only on explicit user direction or a real terminal/operational reason.
- Do not auto-fix review findings. Codex verifies findings and owns edits, tests, commits, and release judgment.
- `grok_delegate` may use tools or modify files. Invoke it only after direct user authorization or an active host policy that inherits a previously approved, exact write boundary. Then inspect the worktree and rerun checks.
- If authentication or model discovery fails, call `grok_setup` and report the exact failing check. Do not silently switch providers or models.
- Job artifacts live under `.grok-companion/jobs/<job-id>/` unless `jobs_dir` overrides it.

## Output Contract

- Launch calls return a durable `job_id`; preserve it until the task reaches a terminal state.
- Policy-selected calls preserve the route receipt, selected role, authorization source, allowed writes, and deterministic acceptance in the task handoff or final evidence packet.
- `grok_wait` returns `completed`, `job_ok`, `next_action`, `status`, and the stored `result` when terminal. A bounded wait timeout is not a job failure: incomplete jobs use `job_ok: null` and `next_action: wait_same_job`. A terminal `job_ok: false` is a failure.
- Review results preserve `verdict`, `summary`, ordered `findings`, and `next_steps` from the public JSON schema.
- Failures preserve exact status, partial output, contract errors, and stderr evidence. Do not substitute a different model or collaborator silently.

## CLI Fallback

Resolve the plugin root from this `SKILL.md`, then use its bundled runtime:

```bash
python3 <plugin-root>/scripts/grb.py ask --background "Explain this error"
python3 <plugin-root>/scripts/grb.py review --background --profile full --base main "Review this branch"
python3 <plugin-root>/scripts/grb.py ask --background --profile quick "Reply with READY only"
python3 <plugin-root>/scripts/grb.py wait <job-id> --timeout 120 --json
python3 <plugin-root>/scripts/grb.py monitor <job-id> --output /absolute/path/grok-job.html --json
python3 <plugin-root>/scripts/grb.py watch <job-id>
python3 <plugin-root>/scripts/grb.py sessions --json
python3 <plugin-root>/scripts/grb.py continue --background --job-id <job-id> "Dig deeper"
```

`superx` remains the focused X/Twitter retrieval and X-native research layer. Grok Companion owns explicit or host-policy-selected general Grok collaboration; keep the surfaces separate.
