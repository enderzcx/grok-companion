# Grok Companion

[中文](./README.md)

Use the local **Grok CLI** as a full external collaborator inside **Codex**.

Grok Companion v0.4.8 is a Codex plugin with 14 native MCP tools, plus an [Agent Plugins](https://agent-plugins.org/) 1.0.0 portable package surface. It covers consultation, structured read-only review, adversarial review, research, delegation, session discovery and continuation, plus durable jobs with an inline Job Monitor.

> **This is not a Codex sidebar terminal.**
>
> It does not embed Grok as a persistent shell or sidebar chat. v0.4 adds a conversation-native Rich Visualization Job Monitor and an optional user-opened terminal `watch`, both backed by the same local `grok` job and artifacts.

The product direction is inspired by [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc). Codex remains the primary install path; the portable core follows Agent Plugins + Agent Skills and is not a Claude Code slash-command plugin.

## Capabilities

| Capability | MCP tool | CLI | Notes |
|---|---|---|---|
| Environment check | `grok_setup` | `setup` | Check `grok`, visible models, jobs, and optional `superx` |
| Ask | `grok_ask` | `ask` | General questions |
| Consult | `grok_consult` | `consult` | Second opinions and tradeoffs |
| Code review | `grok_review` | `review` | Structured findings; read-only contract; no edits |
| Adversarial review | `grok_adversarial_review` | `adversarial-review` | Same schema; challenges assumptions and failure modes |
| Research | `grok_research` | `research` | General source-aware research |
| Delegate | `grok_delegate` | `delegate` | Full local Grok CLI; may use tools or edit files |
| Continue | `grok_continue` | `continue` | Resume by session, companion job, or latest resumable job |
| Session discovery | `grok_sessions` | `sessions` | List or search local Grok CLI sessions |
| Status | `grok_status` | `status` | Inspect jobs without blocking |
| Job Monitor | `grok_monitor` | `monitor` / `watch` | Inspect an inline status snapshot or watch from a terminal |
| Bounded wait | `grok_wait` | `wait` | One bounded wait; re-wait on the same job when incomplete |
| Result | `grok_result` | `result` | Read stored results |
| Cancel | `grok_cancel` | `cancel` | Terminate the runner and its children |

`review` and `adversarial-review` are prompt-level read-only contracts, not an OS sandbox. Codex still owns edits, tests, commits, and shipping; never delegate fixes merely because a review returned findings.

## Why MCP

v0.1 required Codex to shell out to `grb.py`. Since v0.2, the plugin registers a local stdio MCP server so Codex receives first-class `grok_*` tools.

Portable Agent Plugins surface (`plugins/grok-companion/mcp.json`):

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "grok-companion": {
      "type": "stdio",
      "command": "python3",
      "args": ["./scripts/mcp_server.py"],
      "cwd": "${PLUGIN_ROOT}"
    }
  }
}
```

The Codex adapter still uses `.mcp.json`, keeping the same `command` / `args` and adding an `env_vars` allowlist for proxy, certificate, `GROK_BIN`, and jobs-directory variables so the MCP child does not silently lose networking that works in the user's shell.

`mcp_server.py` handles protocol messages, argument validation, and structured results. It delegates every task to `grb.py`, so MCP and CLI share one prompt builder, git-context collector, job model, and artifact format.

The MCP server uses only the Python standard library and needs no additional pip packages.

## Dual packaging

| Surface | Files | Purpose |
|---|---|---|
| Agent Plugins portable core | `plugin.json`, `mcp.json`, `skills/` | Open standard shape for compatible clients |
| Codex adapter | `.codex-plugin/plugin.json`, `.mcp.json`, `.agents/plugins/marketplace.json` | Current Codex install path |
| Publishing convention | [docs/PUBLIC_SKILL_PLUGIN_PUBLISHING.md](./docs/PUBLIC_SKILL_PLUGIN_PUBLISHING.md) | Ender public skill/plugin rules |
| Repo details | [docs/AGENT_PLUGINS.md](./docs/AGENT_PLUGINS.md) | Dual-surface consistency notes |

Personal local skill OS trees under `~/.agents/skills` are **not** mass-migrated to Agent Plugins. Only intentional public distribution units use dual format.

## Background By Default

All MCP launch tools always use background jobs:

```text
Codex calls grok_review / grok_research / grok_continue / ...
        -> receives job_id immediately
        -> local grok runs in the background
        -> grok_wait performs bounded wait windows
        -> returns the stored result when terminal
```

This avoids treating a 25-second-to-multi-minute Grok call as a failed Codex wait and avoids tight `grok_status` polling. Use `grok_status` for non-blocking inspection and the CLI fallback for foreground execution.

Typical flow:

1. Run `grok_setup` when environment or authentication needs checking.
2. Launch `grok_review`, `grok_consult`, or another task and keep the returned `job_id`.
3. Call `grok_wait` with a bounded timeout.
4. If it returns `completed: false`, `job_ok` is `null` and `next_action` is `wait_same_job`; call `grok_wait` again with the same `job_id` and do not cancel or restart the task.
5. Use `grok_cancel` only on explicit user direction or for a real operational reason.

If MCP returns `grb_terminated_by_signal`, `signal_name=SIGKILL` corresponds to the common shell return code `-9`: the local `grb` child was forcibly terminated by the OS or host, not by the Grok job timeout. Check the same `cwd` / `jobs_dir` for an existing job first. Retry only after confirming that no job was created, and restart Codex App if needed to rebuild the MCP process.

Every MCP call requires the absolute current workspace path as `cwd`. Keep `cwd` and an optional `jobs_dir` consistent for the same job.

## Job Monitor

`grok_monitor` renders a Grok job as a Codex inline Rich Visualization with status, elapsed time, remaining budget, profile, turns, self-check mode, process liveness, session, result preview, and refresh, wait, result, cancel, and continue actions. Output is confined to the current workspace or `$CODEX_HOME/visualizations`.

It is a refreshable status snapshot, not a pretend live token stream. The current Grok child writes complete stdout and results after exit; while running, the monitor shows reliable process and budget state. For a terminal view, run `grb.py watch <job-id>`. Stopping the watcher never cancels the Grok job.

## Full And Quick Profiles

When a macOS GUI/MCP host does not inherit shell proxy variables, Grok Companion falls back to the currently enabled system HTTP/HTTPS proxy for Grok child processes. Explicit `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY` values always take precedence; the plugin does not hard-code a machine-specific proxy address.

Formal Grok collaboration defaults to `profile=full`: model `grok-4.6`, the plugin does not pass `--max-turns`, effort defaults to `xhigh`, the job runtime is 7200 seconds, and structured/git context defaults to `context_limit=256000` characters. `review`, `adversarial-review`, and `research` also enable Grok self-check under full. Pass `--effort high` (or lower) when you want a cheaper/faster turn. The goal is a complete Grok collaborator bridge (same product stance as `openai/codex-plugin-cc` for Codex), not a starved one-shot helper.

> Live check (Grok CLI 1.0.3 + default `grok-4.6`): `--effort` accepts `high|medium|low|xhigh`. `grok-4.5` still accepts only `high|medium|low`; the runtime clamps `xhigh` / `max` to `high` on that model (`use one of: high, medium, low`). `context_limit` is the companion embedded-packet budget, not the model context window; do not default to 1M characters.

When the embedded packet is truncated, the prompt tells Grok to tool-read the rest of the repo.

`profile=quick` is an explicit lightweight mode: ordinary tasks use `max_turns=16`, effort `high`, a 900-second job runtime, and no automatic self-check. Use it for connectivity smokes, fixed short answers, or an explicitly requested quick call. Structured `review` and `adversarial-review` are exceptions: even under quick, they remain uncapped unless the caller explicitly supplies `max_turns`.

Read-only `review` / `adversarial-review` jobs recover from explicit `reqwest` streaming transport failures twice by default inside the same total job `timeout`. The initial review is assigned a session; retries use `--resume`, disable tools, reuse completed analysis, and request only the final structured result instead of repeating the whole review. Every attempt, including a timed-out recovery, keeps its stdout/stderr and metadata; the pre-bound session also remains available to `continue` after failure. Other modes do not retry by default, avoiding duplicate writes or external side effects. An exhausted transport failure remains the primary error instead of being mislabeled as a review schema contract failure, and reports top-level `retryable=false` so a host does not restart the whole review again.

Explicit `max_turns`, `timeout`, `context_limit`, `transport_retries`, and `check` values override the profile; structured reviews accept a turn cap only from an explicit `max_turns`. Companion CLI `--check` / `--no-check` and MCP `check: true|false` only control Companion self-check semantics; they are not forwarded as Grok CLI flags. Every mode performs self-check through the task prompt so behavior does not depend on a version-specific Grok CLI option. Job metadata records `check_strategy` as `prompt` or `off`.

A launch tool's `timeout` is the total Grok job runtime. The separate `grok_wait` timeout is only one observation window (default 180 seconds, MCP max 600) and never stops the background job. Explicit `context_limit` raises the embedded git/diff budget when needed.

After an upgrade removes an old versioned cache, already-open tasks may still retain the old MCP process. Starting in 0.4.8, a process whose pinned `grb.py` disappeared selects the highest installed version under the same marketplace/plugin cache root and includes a `runtime_handoff` receipt in the result. A new task is still needed to refresh Skill instructions and MCP schemas, but old tasks no longer lose job management solely because their version directory was replaced.

## Structured Reviews

`grok_review` and `grok_adversarial_review` constrain output with Grok CLI `--json-schema`. The public schema is [`plugins/grok-companion/schemas/review-output.schema.json`](./plugins/grok-companion/schemas/review-output.schema.json).

Required top-level fields are `verdict`, `summary`, `findings`, and `next_steps`. Each finding carries severity, title, body, file, line range, confidence, and a recommendation. Valid JSON is rendered to `result.md` and preserved under `result.json` as `review`; malformed output fails the job with a stored `contract_error`.

## Session Discovery And Continue

Grok `sessionId` values are stored in result and job metadata. `grok_sessions` wraps local `grok sessions list|search`; `grok_continue` resumes in this order:

1. Explicit `session_id`.
2. Session recorded by a companion `job_id`.
3. Latest companion job with a resumable session.

When no session can be recovered, the command fails explicitly instead of silently starting a fresh conversation.

## Use In Codex

After installation, start a new Codex task and ask naturally:

```text
Ask Grok to review my current changes.
Use Grok for an adversarial review of this caching design.
Have Grok research these three options in the background and report back.
Delegate this bounded implementation task to Grok, then verify its work.
Continue the previous Grok session and dig into the second risk.
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
python3 plugins/grok-companion/scripts/grb.py ask --profile quick "Reply with READY only"
python3 plugins/grok-companion/scripts/grb.py wait <job-id> --timeout 120 --json
python3 plugins/grok-companion/scripts/grb.py sessions --json
python3 plugins/grok-companion/scripts/grb.py continue --background --job-id <job-id> "Dig deeper"
python3 plugins/grok-companion/scripts/grb.py status
python3 plugins/grok-companion/scripts/grb.py monitor <job-id> --output /absolute/path/grok-job.html
python3 plugins/grok-companion/scripts/grb.py watch <job-id>
python3 plugins/grok-companion/scripts/grb.py result
python3 plugins/grok-companion/scripts/grb.py cancel <job-id>
```

MCP launch tools always use background execution. The CLI defaults to foreground execution, so add `--background` for long work.

Useful flags include `--profile full|quick`, `--base`, `--include-git-context`, `--jobs-dir`, `--model`, `--effort`, `--max-turns`, `--timeout`, `--check`, `--no-check`, `--tools`, `--disallowed-tools`, `--best-of-n`, and `--session-id`.

Without `--base`, review covers the working tree plus index: unstaged, staged, and untracked text files within the context budget.

## Routing Boundaries

The skill has two activation paths: the user explicitly requests Grok collaboration or is managing an existing job; or the host's active work contract has pre-authorized automatic collaborator selection and the task lead selects Grok for this bounded task. The second path is an opt-in host policy, not authority inferred from work being difficult, cross-file, or review-worthy. Generic review or research with neither activation path, another named AI collaborator, and requests for a sidebar terminal are outside this plugin.

When a host policy selects Grok automatically, emit `🧭 route: <lead> -> Grok <role> | reason: <short reason>` before launch. File-changing work also requires exact allowed writes, deterministic acceptance, and a diff/test budget.

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
codex plugin add grok-companion@enderzcx
```

For local development:

```bash
git clone https://github.com/enderzcx/grok-companion.git
cd grok-companion
codex plugin marketplace add "$PWD"
codex plugin add grok-companion@enderzcx
```

Start a new Codex task after installing or updating. An already open task will not automatically gain newly installed skills and MCP tools.

For v0.4.1 and earlier, the marketplace id was `grok-companion`. Migrate the old registration before reinstalling with `@enderzcx`, otherwise the legacy cache can retain the duplicated name segment:

```bash
codex plugin remove grok-companion@grok-companion
codex plugin marketplace remove grok-companion
codex plugin marketplace add enderzcx/grok-companion --sparse .agents --sparse plugins/grok-companion
codex plugin add grok-companion@enderzcx
```

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
- Delegate uses the full local Grok CLI and may edit files. Invoke it only after direct user authorization or when the host work contract inherits an exact write boundary the user already approved, then inspect and verify all changes.

## Architecture

1. **Agent Plugins portable surface**: `plugin.json`, `mcp.json`, and `skills/`
2. **Codex adapter surface**: `.codex-plugin/plugin.json`, `.mcp.json`, and marketplace
3. **MCP adapter**: `scripts/mcp_server.py`
4. **Job runtime**: `scripts/grb.py`, background processes, and artifacts
5. **Capability adapters**: local Grok CLI, git context, and optional `superx` diagnostics

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) and [docs/AGENT_PLUGINS.md](./docs/AGENT_PLUGINS.md).

## Tests And CI

```bash
python3 -m py_compile plugins/grok-companion/scripts/grb.py plugins/grok-companion/scripts/mcp_server.py scripts/check_release.py
python3 scripts/check_release.py
python3 -m unittest discover -s tests -v
```

Tests use a fake `grok` binary and cover all 14 MCP tools, the Job Monitor, structured review, session continuation, launch -> wait/result, process-tree cancellation, and race regressions. GitHub Actions runs compile, release consistency, and the full suite on Python 3.9 and 3.12.

## Public v0.4 Boundaries

- Requires a working local Grok CLI login.
- MCP is the primary Codex path; CLI is a full fallback over the same runtime.
- Background jobs are local processes plus disk artifacts, not a cloud queue.
- There is no Codex sidebar terminal or persistent REPL.
- `grok_monitor` is an inline status snapshot; the current runtime does not expose live token streaming.
- Review read-only is a prompt contract, not OS-enforced isolation.
- Session continuation depends on locally resumable Grok sessions and is not a cross-machine transfer guarantee.
- Generic review or research that does not name Grok is not auto-routed here.
- Exact X/Twitter work remains the responsibility of `superx`.

## License

[MIT](./LICENSE) · Copyright (c) 2026 Ender

Repo: <https://github.com/enderzcx/grok-companion>
