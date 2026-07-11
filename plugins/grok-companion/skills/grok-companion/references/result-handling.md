# Result Handling

## Launch And Wait

1. Keep the returned `job_id`.
2. Call `grok_wait` once with a bounded wait budget. Do not repeatedly call `grok_status` in a tight loop.
3. If `grok_wait` returns `completed: false`, report that the job is still running and preserve the `job_id`.
4. If it returns `completed: true` with `job_ok: false`, treat the terminal job as failed, timed out, cancelled, or unrecoverable even though the wait operation itself completed.
5. When complete and `job_ok: true`, present the stored result. Do not restart the same task unless the user asks for a fresh run.

## Review Results

- Present findings first, ordered by severity.
- Preserve Grok's file paths, line numbers, confidence, uncertainty, and verdict.
- Say explicitly when there are no findings and mention residual test risk briefly.
- Review is read-only. Do not edit files merely because Grok returned a finding.
- Codex must verify every accepted finding against the current repository before changing code.
- A malformed review contract is a failed review result, even when prose was produced. Report the preserved raw result and contract error.

## Delegate Results

- Inspect the git worktree after Grok exits.
- Re-read every changed file and run relevant checks.
- Do not accept Grok's claim that tests passed without running them from Codex.
- Keep unrelated user changes intact.

## Failures

- MCP unavailable: use the bundled CLI fallback over the same runtime.
- Authentication or model discovery failure: call `grok_setup` and report the exact failing check.
- Job timeout or non-zero exit: preserve partial output and the stderr tail; do not silently rerun with a different model.
- Missing session: use `grok_sessions` or start a fresh task only after saying continuity could not be recovered.
