# Architecture

Grok Companion is split into three layers:

1. Codex plugin surface: `.codex-plugin/plugin.json` and `skills/grok-companion/SKILL.md`.
2. Companion runtime: `scripts/grb.py`, job artifacts, background process control, and result retrieval.
3. Capability adapters: local Grok CLI, git diff/context collection, and optional `superx` diagnostics.

`superx` is intentionally not replaced. It remains the focused X/Twitter retrieval and X-native research wrapper. Grok Companion is the broader collaboration bridge for review, consult, research, and delegation.

## Job Artifacts

Foreground and background runs both create durable artifacts:

```text
.grok-companion/jobs/<job-id>/
  prompt.md
  context.json
  meta.json
  raw.stdout
  raw.stderr
  result.md
  result.json
```

This makes Grok work inspectable by Codex after the process exits, and lets `status`, `result`, and `cancel` work without hidden state.

## Public v0 Boundaries

- The bridge depends on a working local `grok` CLI login.
- `review` and `adversarial-review` are read-only prompts. Codex remains responsible for editing, testing, committing, and shipping.
- Background jobs are local OS processes tracked by pid and artifact state.
- The plugin is a Codex plugin. It is architecturally inspired by `openai/codex-plugin-cc`, but it does not implement Claude Code slash commands.
