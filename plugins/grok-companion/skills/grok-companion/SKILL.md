---
name: grok-companion
description: "Use when the user asks Codex to collaborate with Grok, get Grok's second opinion, run Grok code review/adversarial review, delegate a bounded task to Grok, ask Grok to research, or manage Grok background jobs. This is a general Grok collaborator bridge, not the X/Twitter-only superx route."
when_to_use: "Grok / grb / grok-companion / ask Grok / 让 Grok 看看 / Grok review / Grok adversarial review / Grok consult / Grok delegate / Grok research / Grok status / Grok result / Grok cancel / 用 Grok 跟 Codex 配合"
---

# Grok Companion

Grok Companion lets Codex use the local `grok` CLI as an external collaborator.

It is intentionally broader than `superx`:

- `superx` remains the best route for exact X/Twitter retrieval and X-native tools.
- `grok-companion` is for general collaboration: review, adversarial review, consult, research, delegate, and job management.

## Entrypoint

Resolve this script relative to this file:

```bash
python3 ../../scripts/grb.py --help
```

If you need an absolute path from an installed plugin cache, use the path of this `SKILL.md` and go up two directories to the plugin root, then run:

```bash
python3 <plugin-root>/scripts/grb.py setup
```

## Commands

Use foreground for short work and background for long work:

```bash
python3 <plugin-root>/scripts/grb.py setup
python3 <plugin-root>/scripts/grb.py ask "Explain this error"
python3 <plugin-root>/scripts/grb.py consult --include-git-context "Is this plan sound?"
python3 <plugin-root>/scripts/grb.py review --base main "Review this branch"
python3 <plugin-root>/scripts/grb.py adversarial-review --base main "Challenge the architecture and risk model"
python3 <plugin-root>/scripts/grb.py research --background "Research the current options and report back"
python3 <plugin-root>/scripts/grb.py status
python3 <plugin-root>/scripts/grb.py result
python3 <plugin-root>/scripts/grb.py cancel <job-id>
```

## Codex Usage Rules

- Do not invent in-process Grok tools. Always shell out to `grb.py`.
- Keep long Grok runs in the background when the user does not need the answer immediately.
- `review` and `adversarial-review` are read-only contracts. Codex owns code changes and verification.
- Use `--base main` or another explicit ref when reviewing a branch. Without `--base`, the review covers the working tree and index.
- Use `status` and `result` instead of rerunning the same long job.
- Artifacts live under `.grok-companion/jobs/<job-id>/` in the current git repo, unless `--jobs-dir` or `GROK_COMPANION_JOBS_DIR` overrides it.
- If Grok fails because it is not authenticated, run `grb.py setup --json` and report the exact auth/model error.

## Relationship To superx

For exact X/Twitter status URLs, thread/article fetch, account lookup, keyword search, semantic search, or X-native tool diagnostics, use `superx` first when available.

For general Grok collaboration, use this skill.
