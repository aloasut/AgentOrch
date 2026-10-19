# ORCHESTRATION-PROJECT.md — Per-Project Configuration

> 本文件是本规则包仓库自身的适配层（套件演进项目）。其他项目复用本套件时，应复制本包并按各自情况重写本文件。

## 项目身份

- 项目名称：`Agent-Orchestration Starter Kit（离线单机版）`
- 一句话目标：维护一套可被任意项目复用的单机 Agent 编排规则包：任务状态、路径锁、角色契约与启动/执行/审查方法论。
- 现有项目 / 新项目：现有项目（本仓库即规则包本体）
- 本地主分支：`main`
- 语言 / 框架 / 运行方式：Python 3 标准库（scripts/）；Markdown 规则与提示词文档；无运行时服务。
- 重要设计 / 需求文件：`docs/PROJECT-CHARTER.md`（演进章程）、`AGENTS.md`（权威契约）

## 范围与安全

- 允许改动路径：`prompts/`、`templates/`、`docs/`、`release/`（`release/*.zip` 除外）、`README.md`、`AGENT-BOOTSTRAP.md`、`AGENTS.md`、`MASTER.md`、`AGENT-ORCHESTRATION*.md`、`ORCHESTRATION-PROJECT.md`、`VERSION.txt`、`.gitignore`、`scripts/validate_kit.py`、`scripts/build_release.py`、`tests/`（按任务进一步收窄；`scripts/orchestrator.py` 经 2026-10-12 项目所有者授权，可在当轮质量修复范围内改动，授权依据为质量审核）
- 永远禁止改动路径 / 文件：`LICENSE.txt`、`.orchestration/`；未经授权不得改动 `scripts/orchestrator.py` 的状态机与锁语义
- 授权记录（2026-10-12）：授权人=项目所有者；授权范围=该轮质量修复；限缩说明=本次授权仅覆盖当轮，不改变后续任务的默认边界。
- 秘密与隐私文件模式：`.env*`、`*token*`、`*secret*`、个人绝对路径
- 破坏性操作和迁移政策：禁止对 `.orchestration/state.sqlite3` 做手工 DELETE/UPDATE 绕过 CLI；状态变更只经 `orchestrator.py`
- 新依赖政策：禁止引入任何第三方依赖（保持纯标准库，保证可移植）
- 需要人工批准的变化：角色权限模型改动、AGENTS.md 契约语义变化、破坏 CLI 兼容性的改动

## 验证命令

每条命令已在本机真实探测（Python 路径按机器调整；文档中以 `python` 指代）。

- 快速测试：`python scripts/validate_kit.py`
- 完整回归：`python -m unittest discover -s tests`
- 静态检查 / 类型检查：`python -m py_compile scripts/orchestrator.py scripts/validate_kit.py`（零依赖语法检查；不引入第三方依赖）
- 构建 / 打包：不适用（无构建产物）
- 手工 / UI 冒烟检查：按新提示词走一遍空目录启动冒烟
- 合并后必须执行：快速测试 + 完整回归 + `python scripts/orchestrator.py backup` + 静态检查

## 运行配置

生效值由 `.orchestration/config.json` 提供，`python scripts/orchestrator.py config show` 可查看每个键的生效值与来源；文件缺失或值非法时回落到内置缺省。

- `edition`：`local`（当前）| `github`（保留的托管平台形态；当前实现只支持 `local`）。
- 并发策略：**按机器余量动态决定，不设固定上限**。派发前观察 CPU / 内存 / 磁盘 / 测试资源争用，有余量即可并行；同一 worktree 同一时刻只允许一个测试进程。把「本机实测可承载并发」作为参考记录，而不是规则常量。
- 本地私有目录：`.local/`（`.env`、机器信息、发布扫描规则），永不入库、永不打包。

## 本地工作流

- 分支命名：`task/<ID>-<short-name>`
- Worktree 根目录：`.worktrees/`
- 工作目录要求：一个执行实例一个 Worktree；不共享可写工作区。
- 默认审查修复上限：`3`（只有用户显式修改此值才可改变）
- 本地证据保留方式：`.orchestration/`；日志中需脱敏。
- 备份策略：每阶段结束与每日收尾运行 `python scripts/orchestrator.py backup`，备份保留最近 5 份。

## 通用性要求（本包特有约束）

本仓库的所有 `prompts/`、`templates/` 与规则文档是**可复用产出**：内容必须保持项目无关（不引用本仓库特有的路径、任务 ID 或某次演进决策）；演进决策与背景只写入 `docs/PROJECT-CHARTER.md` 与任务记录。示例中的命令用 `python` 指代解释器路径。

## 新项目启动产物

最少应建立：项目章程 / 范围与非目标、关键假设、架构决策记录（若适用）、目录结构、首个可运行垂直切片、验证方式和后续任务路线。按项目规模调整；不要求为了模板完整而过度文档化。
