# Changelog

All notable changes to Grok Companion are documented here.

## Unreleased

## 0.4.9 - 2026-08-29

- Preserve the public `structuredContent.jobs` shape when a list-returning status call crosses a runtime handoff.
- Accept only complete, manifest-matching plugin packages as replacement runtimes; reject symlink escapes and leftover `grb.py` stubs or shims.
- Mark `grb_runtime_missing` as unsafe to retry blindly and document recovery for launch and job-management calls.

## 0.4.8 - 2026-08-29

- Keep already-running MCP processes usable across marketplace reinstalls: when their pinned versioned `grb.py` is removed, resolve the highest installed runtime under the same plugin cache root and return a `runtime_handoff` receipt.
- Return structured `grb_runtime_missing` evidence when no replacement runtime exists, and cover both the successful hot-upgrade handoff and missing-runtime terminal path with regression tests.

## 0.4.7 - 2026-08-29

- Keep Companion self-check semantics in the task prompt for every mode instead of forwarding the removed Grok CLI `--check` flag; add a regression fake that rejects the stale option.

## 0.4.6 - 2026-08-13

- Default launch model is `grok-4.6`. Product default effort on 4.6 is `xhigh`.
- Clamp `xhigh` / `max` to `high` only when the selected model is still 3-tier (`grok-4.5` and older), so 4.6 jobs can use Extra High without a launch failure.
- Document that cheaper/faster turns should pass `effort=high` (or lower) on 4.6.

- Recover explicit Grok `reqwest` streaming transport failures for read-only structured reviews by resuming a stable session for a tool-free finalization within the existing job timeout, preserve per-attempt artifacts, and stop misclassifying transport failures as review schema contract failures.
- Recover Grok connectivity in macOS GUI/MCP hosts that do not inherit shell proxy variables by falling back to the active system HTTP/HTTPS proxy; explicit proxy environment variables still take precedence.

## 0.4.5 - 2026-08-07

- Hotfix after live CLI verification on Grok 0.2.118 + default `grok-4.5`: default effort is `high` again because `xhigh` and `max` are rejected (`use one of: high, medium, low`).
- Set default embedded `context_limit` to 256000 characters. This is a companion packet budget, not the model context window; do not treat 1M as a safe default.
- Document model-menu effort constraints and the difference between packet size and model context.

## 0.4.4 - 2026-08-07

- Add an Agent Plugins 1.0.0 portable surface: root `plugin.json` and `mcp.json` beside the existing Codex adapter.
- Keep `.codex-plugin/plugin.json` and `.mcp.json` as the Codex install path; release checks now require portable/Codex MCP command parity and matching versions.
- Mark the bundled skill with Agent Skills-compatible optional fields (`license`, `compatibility`, `metadata.agent_plugins`).
- Document dual packaging and the public skill/plugin publishing convention under `docs/`.
- Raise the full-collaborator budget: no turn cap, 7200s job runtime, larger structured git/diff packet, and tool-read guidance when truncated.
- Expand `quick` to 16 turns / 900s for short tasks, keep structured review/adversarial-review uncapped unless `max_turns` is explicit, and expose MCP `context_limit`.
- Align skill/runtime language with a full-collaborator bridge model (inspired by `openai/codex-plugin-cc`), and raise default `grok_wait` observation window to 180s.
- Discover Grok automatically from standard user install paths when the Codex MCP host does not inherit the shell PATH.

## 0.4.3 - 2026-08-03

- Add an opt-in host-policy activation path so a pre-authorized capability-aware router can select Grok without requiring the user to name it again in every task.
- Require visible route receipts and exact inherited write, acceptance, data, and spend boundaries for policy-selected delegation.
- Add positive implicit-routing cases and negative trivial, ambiguous, and sensitive-context cases while keeping ordinary review, research, and exact X retrieval on their existing routes.

## 0.4.2 - 2026-07-24

- Represent an incomplete `grok_wait` as pending with `job_ok: null` and `next_action: wait_same_job`, so agents do not mistake a bounded wait for a failed Grok job.
- Rename the marketplace id to `enderzcx`, avoiding the repeated `grok-companion/grok-companion/<version>` cache path that caused agents to drop one path segment while reading the installed skill.
- Keep terminal failures explicit: only completed jobs can return `job_ok: false`.

## 0.4.1 - 2026-07-18

- Report negative `grb` return codes as structured process-signal diagnostics, including `SIGKILL` for `-9`.
- Mark signal-terminated launch calls as unsafe to retry blindly and direct callers to check durable jobs before relaunching.
- Verify compatibility with Grok CLI 0.2.103.

## 0.4.0 - 2026-07-13

- Add `grok_monitor`, a native MCP tool that renders a responsive Codex inline Job Monitor from durable job state.
- Add `status --detail monitor` and the CLI `watch` command over the same snapshot model.
- Expose status, elapsed time, runtime budget, profile, self-check, process liveness, session continuity, result preview, and conversation-native refresh/wait/result/cancel/continue actions.
- Keep the observation contract honest: current Grok output is captured on process exit, so the monitor identifies itself as a status snapshot rather than a live token stream.

## 0.3.1 - 2026-07-13

- Change unparameterized launch defaults to the `full` profile: 30 turns and a 3600-second job runtime.
- Add an explicit `quick` profile with 6 turns, a 300-second job runtime, and no automatic self-check.
- Enable self-check by default for full review, adversarial review, and research jobs. This release initially used native `--check` for research; the 0.4.7 compatibility fix above supersedes that transport detail with prompt self-check for every mode.
- Teach Codex to continue bounded waits on the same job without premature cancellation or restart.
- Clarify that job runtime and each bounded `grok_wait` window are separate budgets.
- Preserve same-session follow-ups through `grok_continue`; continue jobs resolve their own profile instead of inheriting hidden parent limits.

This release intentionally changes defaults for launch calls that omitted runtime parameters. Explicit runtime flags retain precedence.

## 0.3.0 - 2026-07-12

- Add bounded `grok_wait` long-polling to avoid repeated status calls.
- Add Grok session discovery and resumable `grok_continue` jobs.
- Preserve Grok session IDs in durable result and job metadata.
- Add structured code-review output with a public JSON Schema and Markdown rendering.
- Add routing evals and separate routing/result-handling SOP references.
- Add release consistency checks and GitHub Actions CI.

## 0.2.3 - 2026-07-10

- Forward proxy and certificate environment variables into the MCP server.
- Detach background jobs from MCP stdin.
- Harden setup timeouts, cancellation, path validation, and untracked-file review context.
