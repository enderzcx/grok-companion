# Agent Plugins Dual Surface

Grok Companion ships one portable package root and keeps Codex-native adapters during the transition to [Agent Plugins](https://agent-plugins.org/).

## Package layout

```text
plugins/grok-companion/
├── plugin.json                 # Agent Plugins portable manifest ($schema required)
├── mcp.json                    # Agent Plugins MCP config (type=stdio)
├── .codex-plugin/plugin.json   # Codex marketplace / install adapter
├── .mcp.json                   # Codex MCP adapter (env_vars whitelist)
├── skills/grok-companion/      # Agent Skills layout (one level under skills/)
│   └── SKILL.md
├── scripts/
│   ├── mcp_server.py
│   └── grb.py
└── schemas/
```

## What is portable

| Surface | File | Contract |
|---|---|---|
| Plugin identity | `plugin.json` | Agent Plugins 1.0.0 |
| MCP server | `mcp.json` | Agent Plugins MCP schema |
| Skills | `skills/<name>/SKILL.md` | [Agent Skills](https://agentskills.io/specification) |

Portable rules:

- Keep package paths relative to the plugin root.
- Do not put absolute home paths, secrets, or host-only install instructions into the portable core.
- Prefer `cwd: ${PLUGIN_ROOT}` in `mcp.json`.
- Host credentials remain client-managed; do not encode secrets in package JSON.

## What stays client-specific

| Surface | File | Why |
|---|---|---|
| Codex install metadata | `.codex-plugin/plugin.json` | marketplace `interface`, path overrides |
| Codex MCP host glue | `.mcp.json` | `env_vars` passthrough whitelist |
| Codex marketplace index | `.agents/plugins/marketplace.json` | install selector `grok-companion@enderzcx` |

`plugin.json` points at the Codex adapter through `extensions.com.openai.codex`.

## Consistency rules

Release checks require:

1. `plugin.json.version` == `.codex-plugin/plugin.json.version` == `grb.VERSION` == `mcp_server.SERVER_VERSION`
2. `plugin.json.name` == Codex plugin name == skill directory name == skill frontmatter `name`
3. `mcp.json` and `.mcp.json` share the same `command` and `args`
4. Skill frontmatter stays Agent Skills-valid (`name`, `description` ≤ 1024) with optional `metadata.agent_plugins: "1.0.0"`

## Install paths

Primary production path remains Codex:

```bash
codex plugin marketplace add enderzcx/grok-companion --sparse .agents --sparse plugins/grok-companion
codex plugin add grok-companion@enderzcx
```

Agent Plugins-capable clients can load the portable root at `plugins/grok-companion/` once they implement the open standard. Grok marketplace install remains client-native until Grok adopts Agent Plugins discovery directly.

## Why dual format

Agent Plugins defines the portable floor. Codex already installs through `.codex-plugin` and `.mcp.json`. Dual format avoids breaking current users while making the package ready for Cursor, ChatGPT, GitHub Copilot, and other conforming clients.
