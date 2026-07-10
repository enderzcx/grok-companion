# Grok Companion

[English](./README.en.md)

让 **Codex** 通过本地 `grok` CLI，把 Grok 当作外部协作者使用。

本项目是 **Codex plugin**，结构和产品思路参考 [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc)，但它不是 Claude Code 的 slash-command 插件。核心是一个 Codex skill 加本地 `grb` 桥：Codex 通过 shell 调用 `grb.py`，每次任务都会留下可检查的 job 产物。

## 能做什么

| 命令 | 用途 |
|---|---|
| `ask` | 直接提问 |
| `consult` | 二意见、方案权衡 |
| `review` | 只读代码审查，默认带 git 上下文 |
| `adversarial-review` | 只读对抗式审查，挑战方向、假设和风险 |
| `research` | 研究简报 |
| `delegate` | 委托有边界的任务 |
| `status` | 查看运行中和近期 job |
| `result` | 读取 job 结果 |
| `cancel` | 取消后台 job |
| `setup` | 检查 `grok`、job 目录，可选探测 `superx` |

长任务可加 `--background`。`review` 和 `adversarial-review` 只输出审查结论；改代码、测试、提交和发布仍由 Codex 负责。

## 与 superx 的关系

- **superx**：精确 X/Twitter 抓取、线程、文章、账号与搜索、X 原生工具诊断。X 专用任务优先用 superx。
- **grok-companion**：通用 Grok 协作桥。适合审查、consult、research、delegate 和 job 管理。

二者互补，`grb setup` 可以探测 `superx`，但不会替代它。

## 前置条件

1. 已安装并可用的 Codex。
2. 本机有 Grok CLI：`grok`。
3. 已完成 `grok login`，并且当前账号可用。
4. Python 3。

可选：本机有 `superx` 时，`setup --probe-superx` 可以一起诊断。

## 安装

公开仓库安装：

```bash
codex plugin marketplace add enderzcx/grok-companion --sparse .agents --sparse plugins/grok-companion
codex plugin add grok-companion@grok-companion
```

本地开发：

```bash
git clone https://github.com/enderzcx/grok-companion.git
cd grok-companion
codex plugin marketplace add "$PWD"
codex plugin add grok-companion@grok-companion
```

安装后先检查环境：

```bash
python3 plugins/grok-companion/scripts/grb.py setup
plugins/grok-companion/scripts/grb setup --json
```

## 快速上手

从仓库根目录运行：

```bash
python3 plugins/grok-companion/scripts/grb.py setup
python3 plugins/grok-companion/scripts/grb.py ask "解释这个报错"
python3 plugins/grok-companion/scripts/grb.py consult --include-git-context "这个方案稳吗？"
python3 plugins/grok-companion/scripts/grb.py review --base main "审查当前分支"
python3 plugins/grok-companion/scripts/grb.py adversarial-review --base main "挑战架构与风险模型"
python3 plugins/grok-companion/scripts/grb.py research --background "调研可选方案并回报"
python3 plugins/grok-companion/scripts/grb.py status
python3 plugins/grok-companion/scripts/grb.py result
python3 plugins/grok-companion/scripts/grb.py cancel <job-id>
```

从插件根目录运行：

```bash
python3 scripts/grb.py review --base main "review this branch"
```

常用选项：

| 选项 | 说明 |
|---|---|
| `--base main` | 相对 base 的分支 diff，审查时推荐显式指定 |
| `--include-git-context` | `ask`、`consult` 等非审查模式附带 git 上下文 |
| `--background` | 后台运行并立即返回 `job_id` |
| `--jobs-dir` / `GROK_COMPANION_JOBS_DIR` | 覆盖默认 job 目录 |
| `--model` / `--effort` | 传给本地 `grok` |
| `--format json` | 结构化输出 |

未指定 `--base` 时，审查覆盖工作区和 index，也就是 unstaged + staged diff。

## Job 产物

前台和后台任务都会写入持久化产物，默认在当前 git 仓库根目录：

```text
.grok-companion/jobs/<job-id>/
  prompt.md
  context.json
  meta.json
  raw.stdout
  raw.stderr
  result.md
  result.json
```

- 默认目录：`<repo>/.grok-companion/jobs`
- 可用 `--jobs-dir` 或环境变量 `GROK_COMPANION_JOBS_DIR` 覆盖
- `.grok-companion/` 已在 `.gitignore` 中忽略，避免把本地任务产物提交进仓库

`status`、`result` 和 `cancel` 都依赖这些产物，不依赖隐藏内存状态。

## 架构

三层：

1. **Codex plugin 表面**：`.codex-plugin/plugin.json` 和 `skills/grok-companion/SKILL.md`
2. **Companion 运行时**：`scripts/grb.py`、job 产物、后台进程、结果取回
3. **能力适配**：本地 `grok` CLI、git diff/上下文、可选 `superx` 诊断

详见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)。

## Codex 使用约定

- 不要臆造进程内 Grok 工具；一律 shell 调用 `grb.py`。
- 用户不需要立刻要答案的长任务用 `--background`。
- 审查类命令是只读契约；落地修改与验证归 Codex。
- 用 `status` 和 `result` 续看结果，避免重复开同一长任务。
- 鉴权失败时先跑 `setup --json`，把真实错误报给用户。

## 测试

```bash
python3 -m unittest tests/test_grb.py -v
```

测试使用假 `grok` 二进制，不依赖真实登录。

## 仓库结构

```text
plugins/grok-companion/
  .codex-plugin/plugin.json
  scripts/grb
  scripts/grb.py
  skills/grok-companion/SKILL.md
.agents/plugins/marketplace.json
docs/ARCHITECTURE.md
tests/test_grb.py
```

## v0 边界

- 依赖本机已登录的 `grok` CLI。
- `review` 和 `adversarial-review` 只读；Codex 仍然负责修改、验证和发布。
- 后台 job 是本地 OS 进程，通过 pid 和 artifact 状态跟踪。
- 当前是 Codex plugin，不实现 Claude Code slash commands。

## License

[MIT](./LICENSE) · Copyright (c) 2026 Ender

Repo: <https://github.com/enderzcx/grok-companion>
