# Grok Companion

[中文](./README.md)

Use the local **Grok CLI** as a full external collaborator inside **Codex**.

Grok Companion v0.2 is a Codex plugin with native MCP tools. Codex can call `grok_*` tools for consultation, read-only review, adversarial review, research, delegation, and durable background job management.

> **This is not a Codex sidebar terminal.**
>
> It does not embed Grok as a persistent shell or sidebar chat. The product surface is native MCP tools plus a CLI fallback, backed by the local `grok` process and inspectable job artifacts.

The product direction is inspired by [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc), but this is a Codex plugin, not a Claude Code slash-command plugin.

## Capabilities

| Capability | MCP tool | CLI | Notes |
|---|---|---|---|
| Environment check | `grok_setup` | `setup` | Check `grok`, visible models, jobs, and optional `superx` |
| Ask | `grok_ask` | `ask` | General questions |
| Consult | `grok_consult` | `consult` | Second opinions and tradeoffs |
| Code review | `grok_review` | `review` | Findings only; no edits |
| Adversarial review | `grok_adversarial_review` | `adversarial-review` | Challenge assumptions and failure modes |
| Research | `grok_research` | `research` | General source-aware research |
| Delegate | `grok_delegate` | `delegate` | Full local Grok CLI; may use tools or edit files |
| Status | `grok_status` | `status` | Inspect recent or specific jobs |
| Result | `grok_result` | `result` | Read stored results |
| Cancel | `grok_cancel` | `cancel` | Terminate the runner and its children |

`review` and `adversarial-review` are read-only prompt contracts. Codex still owns edits, tests, commits, and shipping.

## Why MCP

v0.1 required Codex to shell out to `grb.py`. v0.2 registers a local stdio MCP server so Codex receives first-class `grok_*` tools:

```json
{
  "mcpServers": {
    "grok-companion": {
      "command": "python3",
      "args": ["./scripts/mcp_server.py"],
      "cwd": "."
    }
  }
}
```

`mcp_server.py` handles protocol messages, argument validation, and structured results. It delegates every task to `grb.py`, so MCP and CLI share one prompt builder, git-context collector, job model, and artifact format.

The MCP server uses only the Python standard library and needs no additional pip packages.

The plugin uses Codex's `env_vars` allowlist to forward common proxy, certificate, `GROK_BIN`, and jobs-directory variables, so the MCP child does not silently lose networking that works in the user's shell.

## Background By Default

All MCP launch tools always use background jobs:

```text
Codex calls grok_review / grok_research / ...
        -> receives job_id immediately
        -> local grok runs in the background
        -> grok_status reports progress
        -> grok_result returns the stored answer
```

This avoids treating a 25-second-to-multi-minute Grok call as a failed Codex wait and keeps status or cancellation available. Use the CLI fallback when foreground waiting is required.

Typical flow:

1. Run `grok_setup` when environment or authentication needs checking.
2. Launch `grok_review`, `grok_consult`, or another task and keep the returned `job_id`.
3. Call `grok_status` until the job reaches a terminal state.
4. Call `grok_result` for the answer.
5. Use `grok_cancel` to stop early.

Every MCP call requires the absolute current workspace path as `cwd`. Keep `cwd` and an optional `jobs_dir` consistent for the same job.

## Use In Codex

After installation, start a new Codex task and ask naturally:

```text
Ask Grok to review my current changes.
Use Grok for an adversarial review of this caching design.
Have Grok research these three options in the background and report back.
Delegate this bounded implementation task to Grok, then verify its work.
```

Codex prefers the loaded `grok_*` MCP tools. If the MCP server is unavailable, the bundled skill falls back to `grb.py`.

## CLI Fallback

The complete CLI remains available for fallback and debugging:

```bash
python3 plugins/grok-companion/scripts/grb.py setup
python3 plugins/grok-companion/scripts/grb.py ask "Explain this error"
python3 plugins/grok-companion/scripts/grb.py consult --include-git-context "Is this plan sound?"
python3 plugins/grok-companion/scripts/grb.py review --base main "Review this branch"
python3 plugins/grok-companion/scripts/grb.py adversarial-review --base main "Challenge the architecture"
python3 plugins/grok-companion/scripts/grb.py research --background "Research the options"
python3 plugins/grok-companion/scripts/grb.py status
python3 plugins/grok-companion/scripts/grb.py result
python3 plugins/grok-companion/scripts/grb.py cancel <job-id>
```

MCP launch tools always use background execution. The CLI defaults to foreground execution, so add `--background` for long work.

Useful flags include `--base`, `--include-git-context`, `--jobs-dir`, `--model`, `--effort`, `--max-turns`, `--timeout`, `--tools`, `--disallowed-tools`, `--best-of-n`, and `--session-id`.

Without `--base`, review covers the working tree plus index: unstaged, staged, and untracked text files within the context budget.

## Relationship To superx

| | superx | grok-companion |
|---|---|---|
| Role | Exact X/Twitter retrieval and native X tools | General Grok collaboration |
| Prefer for | Status URLs, threads/articles, accounts, keyword/semantic search, X diagnostics | Review, consultation, general research, delegation, jobs |
| Relationship | Separate X-specific route | Can diagnose `superx`, but does not replace it |

Continue to use `superx` first for exact X/Twitter tasks.

## Prerequisites

1. A working Codex installation.
2. The local [Grok CLI](https://x.ai/cli), available as `grok` or configured through `GROK_BIN`.
3. A working `grok login` session with model access.
4. Python 3.9 or newer.

Optional: keep `superx` on `PATH` for combined diagnostics.

## Install

From the public repository:

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

Start a new Codex task after installing or updating. An already open task will not automatically gain newly installed skills and MCP tools.

Environment checks:

```bash
python3 plugins/grok-companion/scripts/grb.py setup --json
python3 plugins/grok-companion/scripts/grb.py setup --probe-superx --json
```

## Job Artifacts

Foreground and background tasks write durable artifacts under the current git repository by default:

```text
.grok-companion/jobs/<job-id>/
  prompt.md
  context.json
  meta.json
  raw.stdout
  raw.stderr
  result.md
  result.json
  runner.stdout
  runner.stderr
```

- Default: `<repo>/.grok-companion/jobs`
- Override with `jobs_dir`, `--jobs-dir`, or `GROK_COMPANION_JOBS_DIR`
- `.grok-companion/` is ignored by git
- Status, result, and cancellation use on-disk state rather than hidden memory
- macOS/Linux cancellation targets the process group; Windows uses `taskkill /T`

## Data And Safety Boundaries

- The companion does not store API keys; it uses the local `grok login` state.
- Prompts, git diffs, stdout/stderr, and results are stored in the local job directory.
- The Grok CLI also sends applicable prompts and context to xAI under the user's account and xAI terms.
- Do not commit or share job directories containing secrets or customer data.
- Review is a prompt-level read-only contract, not an OS sandbox.
- Delegate uses the full local Grok CLI and may edit files. Invoke it only after explicit authorization, then inspect and verify all changes.

## Architecture

1. **Plugin surface**: `.codex-plugin/plugin.json`, `.mcp.json`, and the skill
2. **MCP adapter**: `scripts/mcp_server.py`
3. **Job runtime**: `scripts/grb.py`, background processes, and artifacts
4. **Capability adapters**: local Grok CLI, git context, and optional `superx` diagnostics

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Tests use a fake `grok` binary and cover MCP initialization, discovery of all ten tools, background ask -> status -> result, process-tree cancellation, and the fast-completion race regression.

## Public v0.2 Boundaries

- Requires a working local Grok CLI login.
- MCP is the primary Codex path; CLI is a full fallback over the same runtime.
- Background jobs are local processes plus disk artifacts, not a cloud queue.
- There is no Codex sidebar terminal or persistent REPL.
- There is no custom inline UI yet; one can be added later without replacing the job runtime.
- Exact X/Twitter work remains the responsibility of `superx`.

## License

[MIT](./LICENSE) · Copyright (c) 2026 Ender

Repo: <https://github.com/enderzcx/grok-companion>
