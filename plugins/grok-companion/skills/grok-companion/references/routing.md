# Routing Contract

## Owns

- The user explicitly asks Codex to use Grok, ask Grok, or continue a Grok session.
- The user explicitly requests a Grok second opinion, review, adversarial review, research pass, or bounded delegation.
- The user asks to inspect, wait for, read, or cancel a Grok Companion job.

## Does Not Own

- Generic code review with no Grok request. Use Codex's normal review behavior or the installed review skill.
- Exact X/Twitter URLs, post IDs, accounts, threads, articles, keyword search, semantic search, or native X diagnostics. Use `superx`.
- Generic web research with no Grok request. Use the normal research or web route.
- Requests that explicitly name another collaborator such as Claude, GLM, Kimi, or Gemini.
- Requests for a Grok sidebar terminal or persistent REPL. This plugin exposes MCP tools and a CLI fallback, not an embedded terminal.

## Selection

| Intent | Tool |
|---|---|
| Direct question | `grok_ask` |
| Decision or second opinion | `grok_consult` |
| Code findings over a diff | `grok_review` |
| Challenge assumptions or architecture | `grok_adversarial_review` |
| Source-aware general research | `grok_research` |
| Authorized file-changing work | `grok_delegate` |
| Continue a prior exchange | `grok_continue` |
| Discover Grok sessions | `grok_sessions` |
| Wait without repeated polling | `grok_wait` |

Never use `grok_delegate` merely because a review found an issue. Codex owns whether and how findings are fixed.
