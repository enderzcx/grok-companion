# Ender Public Skill / Plugin Publishing Convention

This is the public packaging contract for Ender/Sunny skills and plugins.

It is intentionally separate from the local skill OS under `~/.agents/skills`. Local routing, EWC paths, Lark login state, and private oracles stay local.

## Decision rule

| Asset type | Publish as | When |
|---|---|---|
| Pure protocol / prompt skill | **Agent Skill** only | No MCP, no multi-component install |
| Skill + MCP / multi-file runtime | **Agent Plugin** (+ client adapters) | One install should load skills and tools together |
| Local-only personal OS skill | Do not publish | Absolute paths, private contracts, host secrets |

Default: keep packages right-sized. Do not wrap every micro skill in a plugin.

## Layering

```text
Local OS (do not mass-migrate)
  ~/.agents/skills/<name>/SKILL.md

Public skill (portable content)
  skills/<name>/SKILL.md          # Agent Skills

Public plugin (portable package)
  plugin.json                     # Agent Plugins
  mcp.json                        # optional
  skills/<name>/...

Client adapters (transition)
  .codex-plugin/plugin.json
  .mcp.json
  .grok-plugin/ or marketplace index
  extensions.com.<vendor>.<client>
```

## Agent Skills minimum

```text
skills/my-skill/
├── SKILL.md
├── scripts/          # optional
├── references/       # optional
├── templates/        # optional
├── assets/           # optional
└── evals/            # optional, for route-confusing skills
```

Frontmatter requirements:

- `name`: lowercase, digits, single hyphens; matches directory name; ≤ 64 chars
- `description`: what + when + exclusions; ≤ 1024 chars
- Optional: `license`, `compatibility` (≤ 500), `metadata` string map

Put Sunny-only fields under `metadata`:

```yaml
metadata:
  short-description: ...
  sunny_skill_type: micro|wrapper|contract|library
  agent_plugins: "1.0.0"   # only when this skill ships inside an Agent Plugin
```

Do not put absolute `/Users/...` paths in public skill bodies. Prefer relative package paths or documented environment variables.

## Agent Plugins minimum

```text
my-plugin/
├── plugin.json
├── mcp.json                 # only if shipping MCP
├── skills/
│   └── my-skill/
│       └── SKILL.md
└── scripts/                 # package-relative helpers
```

`plugin.json` must include:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "my-plugin",
  "version": "0.1.0",
  "description": "...",
  "license": "MIT"
}
```

`mcp.json` must use the Agent Plugins MCP schema, with `type` set (`stdio` or `streamable-http`), package-relative commands, and no secrets.

## Client adapters

Until every target client loads Agent Plugins natively:

| Client | Adapter | Notes |
|---|---|---|
| Codex | `.codex-plugin/plugin.json` + `.mcp.json` | Keep install selectors stable |
| Grok | Grok marketplace / `.grok-plugin` | Client-native until Agent Plugins discovery lands |
| Claude Code | `.claude-plugin` if needed | Only when that distribution path matters |
| Cursor / others | portable core first | Document clone/copy path if plugin install is absent |

Client-specific fields belong in adapter files or `plugin.json.extensions`, not in the portable top-level schema.

## Repo shapes

### A. Single public skill

```text
best-codex/
├── SKILL.md                 # acceptable for pure skills
├── README.md
└── LICENSE
```

Preferred when packaging for multi-client installs:

```text
best-codex/
├── skills/best-codex/SKILL.md
├── README.md
└── LICENSE
```

### B. Skill + MCP plugin

```text
grok-companion/
├── plugins/grok-companion/
│   ├── plugin.json
│   ├── mcp.json
│   ├── .codex-plugin/
│   ├── .mcp.json
│   ├── skills/...
│   └── scripts/...
├── docs/
├── tests/
└── README.md
```

### C. Skill collection / marketplace

```text
ender-plugins/
├── .agents/plugins/marketplace.json   # or .grok-plugin/marketplace.json
└── plugins/
    ├── foo/
    └── bar/
```

## What not to publish

- Skills that hardcode private Ender paths or work contracts
- Skills that require unreleased host policy state to mean anything
- Secrets, customer data, login cookies, or private endpoint tokens
- Duplicate plugin wrappers around unchanged micro skills just for format fashion

## Validation checklist

Before tagging a public skill/plugin:

1. Frontmatter `name` matches directory name
2. Description has triggers and exclusions
3. No absolute personal paths in package files
4. If plugin: `plugin.json` + optional `mcp.json` validate against Agent Plugins 1.0.0
5. If Codex adapter exists: versions and MCP command/args match portable core
6. README documents the primary install path and the portable layout
7. One automated check fails on version or surface drift

Reference implementation: this repository (`grok-companion`).

## Local OS policy

- Keep optimizing `~/.agents/skills` with Sunny classes, registry, and evals
- Do not mass-convert the local catalog into Agent Plugins
- Promote to public packaging only when the asset is intentionally shared and path-clean
