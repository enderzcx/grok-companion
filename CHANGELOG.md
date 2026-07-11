# Changelog

All notable changes to Grok Companion are documented here.

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
