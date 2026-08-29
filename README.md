# Grok Companion

[English](./README.en.md)

让 **Codex** 把本机 **Grok CLI** 当作完整的外部协作者使用。

Grok Companion v0.4.9 是一个带 14 个原生 MCP 工具的 Codex plugin，同时提供 [Agent Plugins](https://agent-plugins.org/) 1.0.0 可移植包装。Codex 可以直接调用 `grok_*` 做 consult、结构化只读 review、adversarial review、research、delegate、session 发现与续聊，以及带 Job Monitor 的后台 job 管理。

> **这不是 Codex 侧边栏终端。**
>
> 它不会把 Grok 嵌成一个常驻 shell 或侧边栏聊天窗口。v0.4 增加了线程内 Rich Visualization Job Monitor，以及可由用户在终端运行的 `watch`；背后仍是同一个本机 `grok` job 与产物模型。

产品方向参考 [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc)。当前主安装路径仍是 Codex plugin；可移植核心遵循 Agent Plugins + Agent Skills，不是 Claude Code slash-command 插件。

## 能做什么

| 能力 | MCP 工具 | CLI | 说明 |
|---|---|---|---|
| 环境检查 | `grok_setup` | `setup` | 检查 `grok`、可见模型和 job 目录，可选探测 `superx` |
| 直接提问 | `grok_ask` | `ask` | 通用问答 |
| 二意见 | `grok_consult` | `consult` | 方案与决策权衡 |
| 代码审查 | `grok_review` | `review` | 结构化 findings；只读契约，不修改代码 |
| 对抗审查 | `grok_adversarial_review` | `adversarial-review` | 同一 schema；挑战方向、假设和失败模式 |
| 深度研究 | `grok_research` | `research` | 通用、源感知 research |
| 有界委托 | `grok_delegate` | `delegate` | 调用完整本机 Grok CLI，可能使用工具或修改文件 |
| 续聊 | `grok_continue` | `continue` | 按 session、companion job 或最近可恢复 job 续写 |
| Session 发现 | `grok_sessions` | `sessions` | 列出或搜索本机 Grok CLI sessions |
| 状态 | `grok_status` | `status` | 非阻塞查看近期或指定 job |
| Job Monitor | `grok_monitor` | `monitor` / `watch` | 在线程内查看状态快照，或在终端持续观察 |
| 有界等待 | `grok_wait` | `wait` | 单次有界等待；未完成时继续等待同一 job |
| 结果 | `grok_result` | `result` | 读取已存储结果 |
| 取消 | `grok_cancel` | `cancel` | 终止后台 runner 及其子进程 |

`review` 和 `adversarial-review` 是 prompt 级只读契约，不是 OS 沙箱。修改代码、测试、提交和发布仍由 Codex 负责；不要因为 review 有 finding 就自动调用 `grok_delegate`。

## 为什么用 MCP

v0.1 需要 Codex 通过 shell 调用 `grb.py`。v0.2 起，插件注册了本地 stdio MCP server，让 Codex 直接获得一组原生 `grok_*` 工具。

可移植 Agent Plugins 表面（`plugins/grok-companion/mcp.json`）：

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

Codex 适配层仍使用 `.mcp.json`，在相同 `command` / `args` 上增加 `env_vars` 白名单，透传代理、证书、`GROK_BIN` 和 jobs-dir，避免本机 Grok 能联网、MCP 子进程却丢失代理配置。

`mcp_server.py` 只负责协议、参数校验和结构化结果，所有实际任务仍交给 `grb.py`。MCP 与 CLI 因此共用同一套 prompt、git context、后台进程和 job 产物，不会形成两套逐渐漂移的实现。

MCP server 仅使用 Python 标准库，不需要额外安装 pip 包。

## 双格式包装

| 表面 | 文件 | 用途 |
|---|---|---|
| Agent Plugins 可移植核心 | `plugin.json`、`mcp.json`、`skills/` | 跨兼容客户端的开放标准形状 |
| Codex 适配 | `.codex-plugin/plugin.json`、`.mcp.json`、`.agents/plugins/marketplace.json` | 当前 Codex 安装与 marketplace |
| 发布约定 | [docs/PUBLIC_SKILL_PLUGIN_PUBLISHING.md](./docs/PUBLIC_SKILL_PLUGIN_PUBLISHING.md) | Ender 公开 skill/plugin 规则 |
| 本仓库细节 | [docs/AGENT_PLUGINS.md](./docs/AGENT_PLUGINS.md) | 双表面一致性与迁移说明 |

本地 `~/.agents/skills` 个人 OS **不**批量迁移到 Agent Plugins；只有像本仓库这样的公开分发单元才做双格式。

## 默认后台任务

所有启动型 MCP 工具都固定使用后台 job：

```text
Codex 调用 grok_review / grok_research / grok_continue / ...
        -> 立即返回 job_id
        -> 本机后台运行 grok
        -> grok_wait 分段有界等待
        -> 终态时直接返回 stored result
```

这让 25 秒到数分钟的 Grok 调用不会被 Codex 的单次等待预算误判为失败，也避免 tight-loop 反复调用 `grok_status`。`grok_status` 仍适合非阻塞查看；需要前台同步执行时使用 CLI 回退。

典型流程：

1. `grok_setup` 检查环境。
2. 调用 `grok_review`、`grok_consult` 或其他启动工具，获得 `job_id`。
3. 调用 `grok_wait`，默认每次最多等待 180 秒（观察窗口，不是 job 总预算）。
4. 若返回 `completed: false`，此时 `job_ok` 为 `null`、`next_action` 为 `wait_same_job`；继续用同一 `job_id` 调用 `grok_wait`，不要取消或重启任务。
5. 只有用户明确要求或存在真实运行原因时才调用 `grok_cancel`。

若 MCP 返回 `grb_terminated_by_signal`，其中 `signal_name=SIGKILL` 对应 shell 常见的退出码 `-9`：这表示本机 `grb` 子进程被系统或宿主强制终止，并不等于 Grok job 自身超时。先在相同 `cwd` / `jobs_dir` 检查是否已有 job；只有确认没有创建 job 后才重试，必要时重启 Codex App 以重建 MCP 进程。

每次 MCP 调用都要使用当前 Codex workspace 的绝对路径作为 `cwd`。同一 job 的 `cwd` 和可选 `jobs_dir` 必须保持一致。

## Job Monitor

`grok_monitor` 把指定 job 渲染为 Codex 线程内的 Rich Visualization：包括状态、已运行时间、剩余预算、profile、turns、自检方式、进程存活、session、结果预览，以及刷新、继续等待、读取结果、取消和续聊操作。输出路径被限制在当前 workspace 或 `$CODEX_HOME/visualizations` 下。

它是可刷新的状态快照，不是假装实时的 token stream。当前 Grok 子进程会在退出后写入完整 stdout 与结果；运行中阶段显示可靠的进程和预算信息。需要自己盯着终端时，可运行 `grb.py watch <job-id>`，退出 watcher 不会取消 Grok job。

## Full 与 Quick

在 macOS GUI / MCP 宿主没有继承 shell 代理变量时，Grok Companion 会读取当前启用的系统 HTTP/HTTPS 代理并仅用于 Grok 子进程。显式的 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY` 始终优先；插件不会硬编码某台机器的代理地址。

正式 Grok 协作默认使用 `profile=full`：模型 `grok-4.6`，插件不主动传 `--max-turns`，`effort=xhigh`，job runtime `timeout=7200` 秒，结构化/git context 默认 `context_limit=256000` 字符。`review`、`adversarial-review` 和 `research` 在 full 下默认开启 Grok 自检。要更快/更省可显式传 `--effort high`。设计目标是让 Grok 作为**完整协作者**工作（类似 `openai/codex-plugin-cc` 对 Codex 的态度），而不是被宿主 turn 预算饿死。

> 实测（Grok CLI 1.0.3 + 默认 `grok-4.6`）：`--effort` 接受 `high|medium|low|xhigh`。`grok-4.5` 仍只接受 `high|medium|low`；对 4.5 传 `xhigh` / `max` 会被 runtime 钳到 `high`（否则 CLI 报 `use one of: high, medium, low`）。`context_limit` 是 companion 塞进 prompt 的字符预算，不是模型上下文窗口；不要默认塞 1M。

若 embedded diff 被截断，prompt 会明确要求 Grok 用工具继续读仓。

`profile=quick` 是显式轻量模式：普通任务使用 `max_turns=16`、`effort=high`、job runtime `timeout=900` 秒，并且不自动开启自检。它适合连通性 smoke、固定短答案或用户明确要求的快速调用。结构化 `review` 和 `adversarial-review` 是例外：即使选择 quick，也不会继承 quick 的 turn cap，只有显式传入 `max_turns` 才会限制轮次。

只读 `review` / `adversarial-review` 遇到明确的 `reqwest` 流式传输错误时，默认在同一 job 的总 `timeout` 预算内恢复 2 次。首次审查预先绑定 session；重试通过 `--resume` 复用已有分析、禁用工具并只收结构化最终结果，避免再次完整审查。每次 attempt（包括恢复阶段超时）都保存 stdout/stderr 与 metadata；预绑定 session 也可供失败后的 `continue` 使用。其他模式默认不自动重试，避免可写或外部副作用被重复执行。最终 transport failure 会保留为主错误，不再被误报成 review schema contract failure；内部恢复预算耗尽后顶层 `retryable=false`，避免宿主再次整单重跑。

显式 `max_turns`、`timeout`、`context_limit`、`transport_retries`、`check` 会覆盖 profile；结构化审查的 turn cap 只接受显式 `max_turns`。Companion CLI 的 `--check` / `--no-check` 与 MCP 的 `check: true|false` 都只控制 Companion 自检语义，不会原样转发给 Grok CLI。所有模式都在 prompt 内执行自检，避免依赖会随 Grok CLI 版本变化的参数。job metadata 的 `check_strategy` 会记录 `prompt` 或 `off`。

这里启动工具的 `timeout` 是整个 Grok job 的运行预算，`grok_wait` 的 `timeout` 只是单次观察窗口（默认 180 秒，MCP 最长 600 秒），不会停止后台 job。

插件升级清理旧版本 cache 后，已经打开的任务可能仍保留旧 MCP 进程。0.4.8 起，旧进程发现其固定 `grb.py` 已不存在时，会在同一 marketplace/plugin cache 根内选择最高已安装的完整插件 runtime 继续执行，并在结果中附带 `runtime_handoff`。0.4.9 保留 `grok_status` 的 `jobs` 结构并拒绝残留 stub/shim。新任务仍用于刷新 Skill 与 MCP schema，但旧任务不会再仅因版本目录被替换而直接失去 job 管理能力。

## 结构化 Review

`grok_review` 和 `grok_adversarial_review` 通过 Grok CLI 的 `--json-schema` 约束输出。公开 schema 位于 [`plugins/grok-companion/schemas/review-output.schema.json`](./plugins/grok-companion/schemas/review-output.schema.json)。

顶层字段为 `verdict`、`summary`、`findings` 和 `next_steps`。每条 finding 包含严重级别、标题、正文、文件、行号、置信度和建议。合法 JSON 会渲染为 `result.md`，并在 `result.json` 保留结构化 `review`；不符合合约的输出会标记为失败并保存 `contract_error`。

## Session 发现与续聊

Grok 返回的 `sessionId` 会保存到 `result.json` 和 job metadata。`grok_sessions` 调用本机 `grok sessions list|search`；`grok_continue` 按以下顺序恢复上下文：

1. 显式 `session_id`。
2. 指定 companion `job_id` 记录的 session。
3. 最近一个带可恢复 session 的 companion job。

找不到 session 时会明确失败，不会悄悄新开一段对话。

## 在 Codex 中使用

安装后新开一个 Codex task，然后直接描述目标：

```text
让 Grok review 当前改动。
让 Grok 对这个缓存方案做 adversarial review。
让 Grok 调研这三个方案，后台跑，完成后告诉我。
把这个有边界的实现任务委托给 Grok，然后由你检查结果。
继续刚才那个 Grok 会话，深挖第二个风险。
```

Codex 会优先调用已加载的 `grok_*` MCP 工具。若 MCP 工具未加载，skill 会回退到 `grb.py`。

## CLI 回退

MCP 不可用或需要直接调试时，可以继续使用完整 CLI：

```bash
python3 plugins/grok-companion/scripts/grb.py setup
python3 plugins/grok-companion/scripts/grb.py ask "解释这个报错"
python3 plugins/grok-companion/scripts/grb.py consult --include-git-context "这个方案稳吗？"
python3 plugins/grok-companion/scripts/grb.py review --base main "审查当前分支"
python3 plugins/grok-companion/scripts/grb.py adversarial-review --base main "挑战架构与风险"
python3 plugins/grok-companion/scripts/grb.py research --background "调研可选方案"
python3 plugins/grok-companion/scripts/grb.py ask --profile quick "只回复 READY"
python3 plugins/grok-companion/scripts/grb.py wait <job-id> --timeout 120 --json
python3 plugins/grok-companion/scripts/grb.py sessions --json
python3 plugins/grok-companion/scripts/grb.py continue --background --job-id <job-id> "深挖第二个风险"
python3 plugins/grok-companion/scripts/grb.py status
python3 plugins/grok-companion/scripts/grb.py monitor <job-id> --output /absolute/path/grok-job.html
python3 plugins/grok-companion/scripts/grb.py watch <job-id>
python3 plugins/grok-companion/scripts/grb.py result
python3 plugins/grok-companion/scripts/grb.py cancel <job-id>
```

MCP 启动工具固定后台；CLI 默认前台，长任务需要显式添加 `--background`。

常用参数包括 `--profile full|quick`、`--base`、`--include-git-context`、`--jobs-dir`、`--model`、`--effort`、`--max-turns`、`--timeout`、`--check`、`--no-check`、`--tools`、`--disallowed-tools`、`--best-of-n` 和 `--session-id`。

未指定 `--base` 时，审查覆盖 working tree + index，包括 unstaged、staged，以及受上下文预算限制的未跟踪文本文件。

## 路由边界

Companion skill 有两个触发入口：用户明确要求 Grok 协作或正在管理已有 job；或者宿主的当前工作合同已经预授权自动选择协作者，并由任务负责人为这个有界任务选中 Grok。第二个入口是宿主主动启用的策略，不会因为任务“复杂、跨文件、值得 review”就自行获得授权。未满足任一入口的普通 code review 和通用 research 不归本插件；点名其他 AI 协作者或要求侧边栏 Grok 终端也不归本插件。

宿主策略自动选中 Grok 时，调用前应留下 `🧭 route: <lead> -> Grok <role> | reason: <short reason>` 回执；文件修改还必须已有精确写入范围、确定性验收与 diff/test budget。

| | superx | grok-companion |
|---|---|---|
| 定位 | 精确 X/Twitter 抓取与 X 原生工具 | 通用 Grok 协作 |
| 优先场景 | status URL、thread/article、账号、keyword/semantic search、X 诊断 | review、consult、通用 research、delegate、job 管理 |
| 关系 | 独立的 X 专用入口 | 可以探测 `superx`，但不替代它 |

精确 X/Twitter 任务继续优先使用 `superx`。

## 前置条件

1. 可用的 Codex。
2. 本机安装了 [Grok CLI](https://x.ai/cli)，命令为 `grok`，或通过 `GROK_BIN` 指定。
3. 已完成 `grok login`，当前账号可正常访问模型。
4. Python 3.9 或更高版本。

可选：PATH 中有 `superx` 时，`grok_setup` 可以一起探测它。

## 安装

公开仓库安装：

```bash
codex plugin marketplace add enderzcx/grok-companion --sparse .agents --sparse plugins/grok-companion
codex plugin add grok-companion@enderzcx
```

本地开发：

```bash
git clone https://github.com/enderzcx/grok-companion.git
cd grok-companion
codex plugin marketplace add "$PWD"
codex plugin add grok-companion@enderzcx
```

安装或更新后请新开一个 Codex task。已经打开的 task 不会自动获得新安装的 skill 和 MCP 工具。

若已安装 v0.4.1 或更早版本，旧 marketplace id 为 `grok-companion`。升级时先迁移旧注册，再按上面的 `@enderzcx` 命令重新安装，避免旧缓存继续生成双层同名路径：

```bash
codex plugin remove grok-companion@grok-companion
codex plugin marketplace remove grok-companion
codex plugin marketplace add enderzcx/grok-companion --sparse .agents --sparse plugins/grok-companion
codex plugin add grok-companion@enderzcx
```

环境检查：

```bash
python3 plugins/grok-companion/scripts/grb.py setup --json
python3 plugins/grok-companion/scripts/grb.py setup --probe-superx --json
```

## Job 产物

前台和后台任务都会写入持久化产物，默认位于当前 git 仓库根目录：

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

- 默认目录：`<repo>/.grok-companion/jobs`
- 可通过 `jobs_dir`、`--jobs-dir` 或 `GROK_COMPANION_JOBS_DIR` 覆盖
- `.grok-companion/` 已被 `.gitignore` 忽略
- `status`、`result` 和 `cancel` 使用磁盘产物，不依赖隐藏内存状态
- macOS/Linux 取消整个 process group；Windows 使用 `taskkill /T`

## 数据与安全边界

- Companion 自身不保存 API key，使用本机 `grok login` 状态。
- prompt、git diff、stdout/stderr 和结果会保存在本地 job 目录。
- 这些内容同时会由 Grok CLI 发往 xAI，并受用户账号与 xAI 条款约束。
- 不要提交或分享含密钥、客户数据或其他敏感内容的 job 目录。
- `review` 是 prompt 级只读约束，不是 OS 沙箱。
- `delegate` 使用完整本机 Grok CLI，并可能修改文件；只在用户直接授权，或宿主工作合同继承了用户已批准的精确写入边界后调用，之后仍需由 Codex 检查和验证。

## 架构

1. **Agent Plugins 可移植表面**：`plugin.json`、`mcp.json`、`skills/`
2. **Codex 适配表面**：`.codex-plugin/plugin.json`、`.mcp.json`、marketplace
3. **MCP 适配层**：`scripts/mcp_server.py`
4. **任务运行时**：`scripts/grb.py`、后台进程与 job artifacts
5. **能力适配**：本机 Grok CLI、git context、可选 `superx` 诊断

详见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) 与 [docs/AGENT_PLUGINS.md](./docs/AGENT_PLUGINS.md)。

## 测试与 CI

```bash
python3 -m py_compile plugins/grok-companion/scripts/grb.py plugins/grok-companion/scripts/mcp_server.py scripts/check_release.py
python3 scripts/check_release.py
python3 -m unittest discover -s tests -v
```

测试使用假 `grok`，覆盖 14 个 MCP 工具、Job Monitor、结构化 review、session 续接、后台 launch -> wait/result、进程树取消和竞态回归。GitHub Actions 在 Python 3.9 与 3.12 上运行编译、release consistency 和全量单测。

## v0.4 边界

- 依赖本机已登录的 Grok CLI。
- MCP 是 Codex 主路径，CLI 是同一运行时的完整回退入口。
- 后台 job 是本地进程 + 磁盘产物，不是云端队列。
- 当前没有 Codex sidebar terminal，也不是长期 REPL。
- `grok_monitor` 是线程内状态快照；当前不提供实时 token stream。
- Review 只读是 prompt 契约，不是 OS 强制隔离。
- Session continue 依赖本机可恢复的 Grok session，不保证跨机器迁移。
- 未点名 Grok 的普通 review/research 不会自动路由到本插件。
- 精确 X/Twitter 仍由 `superx` 负责。

## License

[MIT](./LICENSE) · Copyright (c) 2026 Ender

Repo: <https://github.com/enderzcx/grok-companion>
