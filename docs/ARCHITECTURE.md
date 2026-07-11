# Architecture

Grok Companion has four layers:

1. **Codex plugin surface**: `.codex-plugin/plugin.json`, `.mcp.json`, and `skills/grok-companion/SKILL.md`.
2. **MCP adapter**: `scripts/mcp_server.py` exposes native `grok_*` tools over stdio JSON-RPC.
3. **Companion runtime**: `scripts/grb.py` owns prompts, job creation, background processes, status, results, and cancellation.
4. **Capability adapters**: the local Grok CLI, git diff/context collection, and optional `superx` diagnostics.

The MCP server intentionally delegates every operation to `grb.py`. There is one job model and one artifact format whether Codex calls a native tool or a human runs the CLI.

## Request Flow

```text
Codex task
  -> grok_* MCP tool
  -> mcp_server.py validates arguments
  -> grb.py creates a durable job
  -> local grok CLI runs in the target repository
  -> wait/status/result/cancel read the same job artifacts
```

MCP launch tools always use background execution. The initial call returns quickly with a `job_id`, which avoids treating a long Grok inference as an MCP timeout and keeps status/cancel calls available. Foreground waiting remains available through the CLI fallback.

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
grok_wait
grok_result
grok_cancel
```

Each call receives an explicit absolute `cwd`. This keeps job artifacts and git context attached to the task repository instead of the installed plugin cache.

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
- This plugin does not add a native Codex sidebar terminal. MCP tools appear in Codex tasks; an optional inline job UI can be added later without changing the runtime.
