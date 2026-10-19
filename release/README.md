# 发布标准（Agent-Orchestration 通用分发版本）

本文件定义本套件"通用分发版本"的构建与发布标准。以后每次建 release，都按本文件执行；流程、脚本与清单以本目录为准，产物本身不入库。

## 1. 用途与命名规范

- 用途：把套件打包成可被任意项目复用的通用分发版本；包内只保留与具体项目无关的可复用产出。
- 命名规范：`release/agentorch-{YYYYMMDD}.zip`，`{YYYYMMDD}` 为发布当天日期（例如 `release/agentorch-20261013.zip`）。
- zip 顶层目录固定为 `agentorch-{YYYYMMDD}/`，包内路径相对该目录。
- 产物不纳入 git：`.gitignore` 忽略 `release/*.zip`；仓库只保留流程文档、构建脚本与发布清单（即本文件）。`release/README.md` 不入忽略范围。
- 产物可随时重建：运行 `python scripts/build_release.py`（默认输出到 `release/`）。构建是**可复现**的：同一仓库状态下，包内文件集合、各文件内容与 zip 的 SHA256 均一致（归档时间戳使用固定值），因此发布清单中的 SHA256 可被任何人重建复核。可复现性不依赖检出行尾：构建时文本文件按 LF 归一后打包、二进制文件原样打包（仓库以 `.gitattributes` 统一 LF），故任何检出（含 Windows 上 `core.autocrlf=true`）重建都得到同一 SHA256。

## 2. 包内容规范

- 只含通用可复用产出；不得包含本仓库特有的演进决策、任务记录或个人环境信息。
- 包内文件集合 == `scripts/validate_kit.py` 中的 `REQUIRED` 列表（数量与名称都一致）。该列表是分发内容的唯一来源，构建脚本直接解析它，不再维护第二份清单。
- 发布时 `ORCHESTRATION-PROJECT.md` 自动替换为待填模板 `templates/ORCHESTRATION-PROJECT.template.md`，即分发包总是随附 FILL_IN 模板，首次使用时填写。
- 明确排除（不得出现在包内）：
  - `docs/`：本仓库自有章程与验收记录；
  - `release/`：发布目录本身（含本文件与历史分发包）；
  - `scripts/build_release.py`：构建工具，仅存在于仓库；
  - `.orchestration/`、`.worktrees/`、`.workbuddy/`：机器本地状态；
  - 历史分发包；
  - 个人路径与用户名、本仓库任务 ID、本仓库专有文档名、凭据痕迹等非必要信息。

## 3. 自检清单（发布前必须全过）

自检内置在 `scripts/build_release.py`，随构建自动执行，任何一项失败即非零退出并逐条列出原因；**没有跳过自检的开关**。

- a. 包内容文件集合 == `REQUIRED` 集合（数量与名称一致）。
- b. 解压到临时目录后，`scripts/validate_kit.py` 退出码为 0。
- c. 解压目录内 `scripts/validate_kit.py --project-ready` **预期失败**（退出码 1 且输出含 `FILL_IN`）。这是正确行为而非缺陷：发布的是待填模板；若它"通过"了反而要报错。
- d. 解压目录内 `python -m unittest discover -s tests` 退出码为 0。
- e. 解压目录内 `scripts/orchestrator.py init` 与 `scripts/orchestrator.py task list` 冒烟退出码为 0（`init` 会在临时目录创建 `.orchestration/`，属预期）。
- f. 非必要信息扫描零命中：对包内每个文本文件扫描个人路径与用户名、本仓库任务 ID、本仓库专有文档名与凭据痕迹；并断言包内不存在 `.orchestration/`、`release/`、`scripts/build_release.py`、`docs/` 等结构残留。命中即失败并打印文件与行号。凭据痕迹分两类：`ghp_`、`github_pat_`、`-----BEGIN`、`AKIA` 等精确子串；以及用精确形状正则匹配的 OpenAI 风格密钥——词边界 + `sk-` + 至少 16 位密钥字符（**不使用裸 `sk-` 子串**，否则会误命中 `task-id`、`risk-based`、`subtask-level` 等普通词，误拦正常发布）。此外，断言包内文本文件不含 CRLF（换行统一为 LF），保证构建对检出行尾不敏感；命中即失败并打印文件。
  - 扫描模式分层：**通用模式内置在脚本**（个人主目录、凭据形状等，任何克隆都适用）；**机器 / 本仓库相关模式放在 `.local/release-scan.json`**（`{"forbidden_patterns": [...]}`，逐条按精确子串匹配）。该文件缺失时跳过本地规则并打印 `extra scan patterns: none`；该文件永不入库、永不打包。
- g. 结束时打印清单：包内文件数、zip 路径、zip 大小（字节）、zip 的 SHA256（SHA256 用于复核：同一仓库状态下重建应得到同一值）。

自检失败时，脚本会**删除刚生成的、未通过自检的 zip**，并在失败信息中说明"已删除未通过自检的产物"（若删除失败则如实打印该产物路径），确保 `release/` 不会留下被误当发布物的半成品。

## 4. 发布流程

1. 在任务库登记发布任务（唯一 ID、单一目标、允许路径与验收）。
2. 从最新本地主分支创建独立分支 / Worktree；不在共享工作区直接构建。
3. 构建：运行 `python scripts/build_release.py` 生成 `release/agentorch-{YYYYMMDD}.zip`。
4. 自检：确认脚本内置 a–f 全部通过并记录退出码；产物路径、字节数与 SHA256 一并留证。
5. Master 独立审查（逐条对照本文件的自检清单与验收标准）。
6. 合并到本地主分支；合并后重新运行验证并记录结果。
7. 在下方"发布清单"登记条目。
8. 发布后清理本任务分支 / Worktree（独立记账，清理由此与"合并成功"分开记录）。

## 5. 发布清单

| 文件 | 日期 | 来源提交 | 大小(字节) | SHA256 |
| --- | --- | --- | --- | --- |
| release/agentorch-20261013.zip | 2026-10-13 | bcd30e59099cabc84b50c53bd14db1539457d835 | 46599 | 7552e0c1cf437110055f55b09f78dc73f8fb4e4d4e07e56cbbd61081a670bcd6 |
| release/agentorch-20261019.zip | 2026-10-19 | d70ea36d912e3caca442aa6e74a5f912972c0c30 | 82603 | 8751fbd6f7df37ba00317d4ef8814a04272489fd252a4365436529ee4fa7e5ba |

v1.1 相对 v1.0 的变化要点：双底座（`editions/local` 与 `editions/github` 并列，共用同一套核心契约）、`.local/` 隐私层（本机私有文件永不入库、永不打包）、按机器余量决定并发（不设固定上限）、配置自省（`orchestrator.py config show` 显示生效值与来源）、扫描模式分层（通用模式内置在构建脚本，机器 / 本仓库相关模式放 `.local/release-scan.json`）。

表中每一项均可在其"来源提交"上重建，并得到同一 SHA256（需使用同一 Python 版本）。构建对**检出状态不敏感**：文本文件按 LF 归一打包、二进制原样打包，仓库以 `.gitattributes` 统一 LF，因此任何检出（含 Windows 上 `core.autocrlf=true`）重建都得到同一 SHA256。

## 6. 声明

以后建 release 就按本文件执行：命名、包内容、自检、流程与清单全部以本文件为准；任何偏离都必须先更新本文件并说明理由。
