---
name: grok-companion
description: "Use when the user explicitly asks Codex to collaborate with Grok, get Grok's second opinion, run a Grok review or adversarial review, continue a Grok session, delegate a bounded task to Grok, research with Grok, or manage Grok Companion jobs. Not for generic code review or generic web research that does not name Grok, exact X/Twitter retrieval or search (use superx), another named AI collaborator, or requests for a sidebar terminal."
metadata:
  short-description: Use Grok as a managed Codex collaborator
---

# Grok Companion

Use the local `grok` CLI as an external Codex collaborator through native MCP tools and one durable job runtime.

## Before Calling

Read [references/routing.md](references/routing.md) when ownership is ambiguous. The key boundary is explicit intent: do not route ordinary review or research to Grok unless the user named Grok or is already managing a Grok Companion job.

For exact X/Twitter URLs, posts, accounts, threads, articles, search, or X-native diagnostics, use `superx` instead.

## Call Path

1. Prefer visible `grok_*` MCP tools.
2. Pass the absolute current workspace as `cwd` on every call.
3. Use `profile=full` by default. It resolves to 30 turns and a 3600-second job runtime; review, adversarial review, and research also self-check. Do not lower these budgets merely to fit the current Codex turn.
4. Use `profile=quick` only for a connectivity smoke, a deliberately small fixed-answer task, or an explicit user request. It resolves to 6 turns, 300 seconds, and no automatic self-check.
5. Launch tools return a background `job_id`.
6. Call `grok_wait` with a bounded timeout. If it returns `completed: false`, call it again with the same `job_id`. Avoid tight `grok_status` polling.
7. When the user wants to see Grok working, call `grok_monitor` with the job and an absolute `.html` path in the current Codex visualization directory, then present that file as an inline visualization. Refreshing renders a new snapshot; it is not a live token stream.
8. Follow [references/result-handling.md](references/result-handling.md) when presenting or accepting results.
9. Use the bundled `scripts/grb.py` CLI only when MCP is unavailable or foreground execution is specifically required.

Explicit `max_turns`, job `timeout`, and `check` values override the selected profile. The launch `timeout` is Grok's total job runtime; the `grok_wait` timeout is only one bounded observation window and never cancels the job.

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
- `grok_delegate`: explicitly authorized bounded work that may edit files.
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
- `grok_delegate` may use tools or modify files. Invoke it only after explicit user authorization, then inspect the worktree and rerun checks.
- If authentication or model discovery fails, call `grok_setup` and report the exact failing check. Do not silently switch providers or models.
- Job artifacts live under `.grok-companion/jobs/<job-id>/` unless `jobs_dir` overrides it.

## Output Contract

- Launch calls return a durable `job_id`; preserve it until the task reaches a terminal state.
- `grok_wait` returns `completed`, `job_ok`, `status`, and the stored `result` when terminal. A bounded wait timeout is not a job failure; continue waiting on the same job. A terminal `job_ok: false` is a failure.
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

`superx` remains the focused X/Twitter retrieval and X-native research layer. Grok Companion owns explicit general Grok collaboration; keep the surfaces separate.
