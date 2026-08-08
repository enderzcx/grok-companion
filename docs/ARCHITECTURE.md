# Architecture

Grok Companion has five layers:

1. **Portable Agent Plugins surface**: root `plugin.json`, `mcp.json`, and `skills/grok-companion/SKILL.md` (Agent Skills layout).
2. **Codex adapter surface**: `.codex-plugin/plugin.json`, `.mcp.json`, and the marketplace index under `.agents/plugins/`.
3. **MCP adapter**: `scripts/mcp_server.py` exposes native `grok_*` tools over stdio JSON-RPC.
4. **Companion runtime**: `scripts/grb.py` owns prompts, job creation, background processes, status, results, and cancellation.
5. **Capability adapters**: the local Grok CLI, git diff/context collection, and optional `superx` diagnostics.

The portable and Codex surfaces must stay version-aligned. See [AGENT_PLUGINS.md](./AGENT_PLUGINS.md).

The MCP server intentionally delegates every operation to `grb.py`. There is one job model and one artifact format whether Codex calls a native tool or a human runs the CLI.

## Request Flow

```text
Codex task
  -> grok_* MCP tool
  -> mcp_server.py validates arguments
  -> grb.py creates a durable job
  -> local grok CLI runs in the target repository
  -> wait/status/monitor/result/cancel read the same job artifacts
```

MCP launch tools always use background execution. The initial call returns quickly with a `job_id`, which avoids treating a long Grok inference as an MCP timeout and keeps status/cancel calls available. Foreground waiting remains available through the CLI fallback.

On macOS, `grb.py` preserves explicit proxy environment variables and otherwise translates the active `scutil --proxy` HTTP/HTTPS configuration into standard proxy variables before any Grok setup, foreground, or background subprocess starts. This closes the GUI-host gap without embedding machine-specific proxy values in the plugin manifest.

Runtime profiles are resolved once in `grb.py`, then persisted as concrete `profile`, `max_turns`, `effort`, `timeout`, and `check` job metadata. MCP forwards only user-supplied fields. The default `full` profile leaves `max_turns` unset so the plugin does not impose a turn cap, defaults effort to `high` (the highest level currently accepted by default `grok-4.5`), uses a 7200-second job runtime, and embeds up to 256000 characters of git/diff context for structured review. That packet budget is not the model context window. `quick` uses 16 turns, effort `high`, and 900 seconds for ordinary short tasks. Structured `review` and `adversarial-review` never inherit quick's turn cap: only an explicit `max_turns` limits them. When embedded context is truncated, the prompt tells Grok to tool-read the remainder instead of pretending the packet is complete. Explicit fields override profile values.

Self-check intent is persisted separately from transport as `check_strategy`. Research can use Grok's native `--check`. Structured review modes use an equivalent prompt self-check because the current Grok CLI rejects `--check` together with `--json-schema`; this preserves valid structured output instead of failing at launch.

Job runtime and waiting are intentionally separate. `grok_wait` observes one bounded window (default 180 seconds, MCP max 600). An incomplete window never cancels or restarts the background job; clients continue waiting with the same `job_id` until a terminal state or preserve the running job during handoff.

`grok_wait` performs one bounded long-poll over the same disk state and returns the terminal result when available. This keeps agents from issuing tight `grok_status` loops. A timed-out wait does not cancel or restart the job.

## MCP Surface

The stdio server uses only the Python standard library and implements the MCP initialize, ping, tool listing, and tool call paths needed by Codex. The plugin exposes:

```text
grok_setup
grok_ask
grok_consult
grok_review
grok_adversarial_review
grok_research
grok_delegate
grok_continue
grok_sessions
grok_status
grok_monitor
grok_wait
grok_result
grok_cancel
```

Each call receives an explicit absolute `cwd`. This keeps job artifacts and git context attached to the task repository instead of the installed plugin cache.

## Observation Surfaces

`grok_status --detail monitor` builds a bounded snapshot from job metadata and stored artifacts. `grok_monitor` injects that snapshot into the bundled `job-monitor.html` fragment so Codex can present a responsive, conversation-native Rich Visualization. Its buttons use `window.openai.sendFollowUpMessage` to ask Codex to refresh, wait, read, cancel, or continue the same job.

The current Grok subprocess is captured until exit, so the monitor explicitly reports `stream_available: false`. It shows process liveness, elapsed time, runtime budget, profile, self-check mode, session, and any stored result preview. It does not claim progressive token streaming. Monitor files are confined to the current workspace or `$CODEX_HOME/visualizations`. The CLI `watch` command renders the same snapshot model in a user-opened terminal and stopping the watcher does not cancel the job.

## Structured Reviews

Review modes pass `schemas/review-output.schema.json` to Grok CLI through `--json-schema`. The runtime accepts either a direct schema object or a JSON object nested in the CLI response envelope, renders it to `result.md`, and preserves the original structure in `result.json`. A malformed contract produces a failed job with raw output retained for diagnosis.

## Session Continuity

The runtime extracts `sessionId` or `session_id` from Grok JSON output and stores it in both result and job metadata. `grok_sessions` exposes local Grok session discovery. `grok_continue` creates a normal durable job while resolving its resume target from an explicit session id, a prior companion job, or the latest resumable companion job.

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
  runner.stdout
  runner.stderr
```

The files make Grok work inspectable after either process exits. Background jobs run in their own process group so cancellation terminates the runner and its Grok child together.

## Safety Boundaries

- The bridge depends on a working local `grok` CLI login and uses that CLI's model access and network behavior.
- `review` and `adversarial-review` are read-only prompt contracts. Codex remains responsible for editing, testing, committing, and shipping.
- Read-only review is not OS-enforced isolation. Structured output improves the result contract, not process permissions.
- `delegate` can use the full local Grok CLI and may modify files; Codex must inspect and verify delegated changes.
- The MCP process runs locally. Repository context and prompts are sent to the local Grok CLI, which may send them to xAI under the user's Grok account and applicable terms.
- `superx` is not replaced. It remains the focused X/Twitter retrieval and X-native research wrapper.
- This plugin does not add a native Codex sidebar terminal. MCP tools appear in Codex tasks, and `grok_monitor` provides the supported inline observation surface without changing the durable job runtime.
