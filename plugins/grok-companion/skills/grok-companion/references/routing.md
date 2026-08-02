# Routing Contract

## Owns

- The user explicitly asks Codex to use Grok, ask Grok, or continue a Grok session.
- The user explicitly requests a Grok second opinion, review, adversarial review, research pass, or bounded delegation.
- The user asks to inspect, wait for, read, or cancel a Grok Companion job.
- An active host policy has pre-authorized automatic collaborator selection, the task lead selects Grok, and the selected role stays inside that policy's approved task, write, data, spend, and acceptance boundaries.

## Does Not Own

- Generic code review with neither an explicit Grok request nor a host-policy selection. Use Codex's normal review behavior or the installed review skill.
- Exact X/Twitter URLs, post IDs, accounts, threads, articles, keyword search, semantic search, or native X diagnostics. Use `superx`.
- Generic web research with neither an explicit Grok request nor a host-policy selection. Use the normal research or web route.
- Requests that explicitly name another collaborator such as Claude, GLM, Kimi, or Gemini.
- Requests for a Grok sidebar terminal or persistent REPL. This plugin exposes MCP tools and a CLI fallback, not an embedded terminal.

## Host-Policy Selection

Host-policy selection is valid only when all of these are true:

- The active host contract explicitly allows automatic collaborator selection; general task complexity is not authorization.
- The task lead names Grok's bounded role and emits `🧭 route: <lead> -> Grok <role> | reason: <short reason>` before launch.
- File-changing work has exact allowed writes, deterministic acceptance, and a diff/test budget already covered by the user's approved boundary.
- Prompts and context can be sent without secrets, credentials, raw customer data, or unredacted production logs.
- The route creates no unapproved external write, metered spend, purchase, permission change, or release action.

Keep the current lead or use the host's native route when the task is trivial and localized, acceptance or write scope is unclear, live or dirty state cannot be safely packetized, sensitive context cannot be redacted, the external-write or spend boundary is not approved, or Grok is unavailable. State the host's required skip receipt instead of silently pretending Grok ran.

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

Never use `grok_delegate` merely because a review found an issue. The user or active host contract must separately authorize the bounded writes, and the task lead owns whether and how findings are fixed.
