---
name: grok-companion
description: "Use when the user asks Codex to collaborate with Grok, get Grok's second opinion, run Grok code review/adversarial review, delegate a bounded task to Grok, ask Grok to research, or manage Grok background jobs. This is a general Grok collaborator bridge, not the X/Twitter-only superx route."
---

# Grok Companion

Grok Companion lets Codex use the local `grok` CLI as a general external collaborator. It provides native MCP tools plus a shell fallback over the same durable job runtime.

## Route Priority

1. When the `grok_*` MCP tools are visible, use them first.
2. If the MCP server is not loaded or fails to start, shell out to `scripts/grb.py`.
3. For exact X/Twitter retrieval, account lookup, status/thread/article URLs, search, or X-native diagnostics, use `superx` instead.

Do not invent tool names that are not present in the current session.

## Native MCP Tools

- `grok_setup`: check Grok CLI, models, job directory, and optional superx diagnostics.
- `grok_ask`: direct question.
- `grok_consult`: second opinion and tradeoff analysis.
- `grok_review`: read-only code review.
- `grok_adversarial_review`: read-only challenge review.
- `grok_research`: source-aware research.
- `grok_delegate`: bounded delegation with the full local Grok CLI.
- `grok_status`: inspect recent or running jobs.
- `grok_result`: read a stored result.
- `grok_cancel`: cancel a background job and its process tree.

Every MCP call requires the absolute current workspace path as `cwd`. Launch tools always run in the background and return a `job_id`. Use `grok_status` and then `grok_result`; do not restart the same task merely because it is still running. Use the CLI fallback when foreground waiting is specifically required.

## Review And Delegation Rules

- `grok_review` and `grok_adversarial_review` are read-only contracts. Codex owns fixes, tests, commits, and release judgment.
- Use `base: "main"` or another explicit ref for branch review. Without a base, review covers unstaged plus staged changes.
- `grok_delegate` can invoke the full local Grok CLI and may use tools or modify files. Use it only when the user authorized delegation, then inspect and verify every change before accepting it.
- Job artifacts live under `.grok-companion/jobs/<job-id>/` in the target repo unless `jobs_dir` overrides it.
- If authentication or model discovery fails, run `grok_setup` and report the exact result.

## Shell Fallback

Resolve the plugin root from this `SKILL.md`, then run:

```bash
python3 <plugin-root>/scripts/grb.py setup
python3 <plugin-root>/scripts/grb.py ask --background "Explain this error"
python3 <plugin-root>/scripts/grb.py consult --background --include-git-context "Is this plan sound?"
python3 <plugin-root>/scripts/grb.py review --background --base main "Review this branch"
python3 <plugin-root>/scripts/grb.py adversarial-review --background --base main "Challenge the architecture"
python3 <plugin-root>/scripts/grb.py research --background "Research the options"
python3 <plugin-root>/scripts/grb.py status
python3 <plugin-root>/scripts/grb.py result
python3 <plugin-root>/scripts/grb.py cancel <job-id>
```

## Relationship To superx

`superx` remains the focused X/Twitter retrieval and X-native research layer. Grok Companion is the broader collaboration layer for review, consult, research, delegation, and managed jobs. Keep both surfaces separate.
