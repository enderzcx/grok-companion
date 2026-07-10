# Grok Companion

[中文](./README.md)

A **Codex plugin** plus local **`grb` bridge** that lets Codex use the local **Grok CLI** as an external collaborator.

This project is a Codex plugin. Its structure and product direction are inspired by [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc), but it is not a Claude Code slash-command plugin. Codex shells out to `grb.py`; every run leaves inspectable job artifacts on disk.

## What It Does

| Command | Purpose |
|---|---|
| `ask` | Direct question |
| `consult` | Second opinion and tradeoff review |
| `review` | Read-only code review with git context |
| `adversarial-review` | Read-only challenge review for direction, assumptions, and risk |
| `research` | Research brief |
| `delegate` | Bounded task handoff |
| `status` | Running and recent jobs |
| `result` | Print a job result |
| `cancel` | Cancel a background job |
| `setup` | Check `grok`, jobs directory, and optional `superx` |

Use `--background` for long work. `review` and `adversarial-review` only produce findings; Codex still owns edits, tests, commits, and shipping.

## Relationship To superx

- **superx**: exact X/Twitter fetch, threads, articles, account/search, and X-native tool diagnostics. Prefer superx for X-specific tasks.
- **grok-companion**: general Grok collaboration. Use it for review, consult, research, delegate, and job control.

They complement each other. `grb setup` can probe `superx`; it does not replace it.

## Prerequisites

1. Working Codex.
2. Local Grok CLI: `grok`.
3. Completed `grok login`, with a working account.
4. Python 3.

Optional: if `superx` is on `PATH`, `setup --probe-superx` can include it in diagnostics.

## Install

From the public GitHub repo:

```bash
codex plugin marketplace add enderzcx/grok-companion --sparse .agents --sparse plugins/grok-companion
codex plugin add grok-companion@grok-companion
```

For local development:

```bash
git clone https://github.com/enderzcx/grok-companion.git
cd grok-companion
codex plugin marketplace add "$PWD"
codex plugin add grok-companion@grok-companion
```

After install, verify the environment:

```bash
python3 plugins/grok-companion/scripts/grb.py setup
plugins/grok-companion/scripts/grb setup --json
```

## Quick Start

From the repository root:

```bash
python3 plugins/grok-companion/scripts/grb.py setup
python3 plugins/grok-companion/scripts/grb.py ask "Explain this error"
python3 plugins/grok-companion/scripts/grb.py consult --include-git-context "Is this plan sound?"
python3 plugins/grok-companion/scripts/grb.py review --base main "Review this branch"
python3 plugins/grok-companion/scripts/grb.py adversarial-review --base main "Challenge the architecture and risk model"
python3 plugins/grok-companion/scripts/grb.py research --background "Research options and report back"
python3 plugins/grok-companion/scripts/grb.py status
python3 plugins/grok-companion/scripts/grb.py result
python3 plugins/grok-companion/scripts/grb.py cancel <job-id>
```

From the plugin root:

```bash
python3 scripts/grb.py review --base main "review this branch"
```

Useful flags:

| Flag | Meaning |
|---|---|
| `--base main` | Branch diff against a base ref, recommended for reviews |
| `--include-git-context` | Attach git context for non-review modes |
| `--background` | Start and return `job_id` immediately |
| `--jobs-dir` / `GROK_COMPANION_JOBS_DIR` | Override jobs directory |
| `--model` / `--effort` | Forwarded to local `grok` |
| `--format json` | Structured output |

Without `--base`, reviews cover the working tree and index, meaning unstaged + staged diffs.

## Job Artifacts

Foreground and background runs both write durable files, by default under the current git root:

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

- Default: `<repo>/.grok-companion/jobs`
- Override with `--jobs-dir` or `GROK_COMPANION_JOBS_DIR`
- `.grok-companion/` is ignored in `.gitignore`, so local job output is not committed

`status`, `result`, and `cancel` use these artifacts. There is no hidden in-memory state.

## Architecture

Three layers:

1. **Codex plugin surface**: `.codex-plugin/plugin.json` and `skills/grok-companion/SKILL.md`
2. **Companion runtime**: `scripts/grb.py`, job artifacts, background processes, and result retrieval
3. **Adapters**: local `grok` CLI, git diff/context, and optional `superx` diagnostics

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

## Codex Usage Rules

- Do not invent in-process Grok tools; always shell out to `grb.py`.
- Prefer `--background` for long runs when the user does not need the answer immediately.
- Review modes are read-only contracts; Codex owns changes and verification.
- Use `status` and `result` instead of re-running the same long job.
- On auth failure, run `setup --json` and report the exact error.

## Tests

```bash
python3 -m unittest tests/test_grb.py -v
```

Tests use a fake `grok` binary; no live login is required.

## Layout

```text
plugins/grok-companion/
  .codex-plugin/plugin.json
  scripts/grb
  scripts/grb.py
  skills/grok-companion/SKILL.md
.agents/plugins/marketplace.json
docs/ARCHITECTURE.md
tests/test_grb.py
```

## Public v0 Boundaries

- Depends on a working local `grok` CLI login.
- `review` and `adversarial-review` are read-only; Codex remains owner of edits and shipping.
- Background jobs are local OS processes tracked by pid and artifact state.
- This is a Codex plugin. It does not implement Claude Code slash commands.

## License

[MIT](./LICENSE) · Copyright (c) 2026 Ender

Repo: <https://github.com/enderzcx/grok-companion>
