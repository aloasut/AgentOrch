# 发布标准（Agent-Orchestration 通用分发版本）

本文件定义本套件"通用分发版本"的构建与发布标准。以后每次建 release，都按本文件执行；流程与脚本以本目录为准，产物本身不入库。

## 1. 用途与命名规范

- 用途：把套件打包成可被任意项目复用的通用分发版本；包内只保留与具体项目无关的可复用产出。
- 命名规范：`release/agentorch-{YYYYMMDD}.zip`，`{YYYYMMDD}` 为发布当天日期。
- zip 顶层目录固定为 `agentorch-{YYYYMMDD}/`，包内路径相对该目录。
- 产物不纳入 git：`.gitignore` 忽略 `release/*.zip`；仓库只保留流程文档、构建脚本与本标准；历史版本记录由 GitHub Releases 承担。`release/README.md` 不入忽略范围。
- 产物可随时重建：运行 `uv run python scripts/build_release.py`（默认输出到 `release/`）。构建是**可复现**的：同一仓库状态下，包内文件集合、各文件内容与 zip 的校验和均一致（归档时间戳使用固定值），因此 zip 的校验和可被任何人重建复核。可复现性不依赖检出行尾：构建时文本文件按 LF 归一后打包、二进制文件原样打包（仓库以 `.gitattributes` 统一 LF），故任何检出（含 Windows 上 `core.autocrlf=true`）重建都得到同一校验和。

## 2. 包内容规范

- 只含通用可复用产出；不得包含本仓库特有的演进决策、任务记录或个人环境信息。
- 包内文件集合 == `scripts/validate_kit.py` 中的 `REQUIRED` 列表 **+ 构建时生成的 `MANIFEST.json`**（数量与名称都一致，即 `len(REQUIRED) + 1` 个文件）。`REQUIRED` 是分发内容的唯一来源，构建脚本直接解析它，不再维护第二份清单；`MANIFEST.json` 是唯一不来自 `REQUIRED` 的成员。
- **`MANIFEST.json`（机器可读清单）**：由 `scripts/check_drift.py` 生成，构建脚本导入该模块而不另写一份规则，因此分类只有一处实现。字段固定为：
  - 顶层 `schema_version`（清单格式版本）、`suite`（套件名，取自 `VERSION.txt`）、`format_version`（套件格式版本，当前 `1.3`）、`files[]`；
  - 条目 `path`、`category`、`sha256`、`size`（`sha256` 与 `size` 按包内实际字节计算，文本已按 LF 归一）；
  - `category` 只允许四种上游分类：`editions/` 前缀 → `edition`，`templates/` 前缀 → `template`，`ORCHESTRATION-PROJECT.md` / `PLAN.md`（旧根位置）/ `docs/PLAN.md`（1.4 起）/ `DESIGN.md` → `project-profile`，其余 → `core`；
  - 清单**不列出自身**（无法嵌入自己的哈希）、**不含时间戳**、条目按路径排序，因此同一仓库状态两次构建得到逐字节相同的清单。
- **`check_drift.py` 的只读边界**：该脚本随包发布，供下游项目做漂移诊断。它只读取（`read_bytes` / `read_text`）、列目录，**从不创建、重命名、删除或写入项目根下的任何文件**；诊断只报告差异与建议，是否对齐由项目所有者决定。
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

- a. 包内容文件集合 == `REQUIRED` + `MANIFEST.json`（数量与名称一致）；解压后 `MANIFEST.json` 必须能解析每条 `path`、`sha256` 与 `size` 与实际文件一致、`category` 只用合法分类，且清单列出的路径集合与 `REQUIRED` 完全一致。
- b. 解压到临时目录后，`scripts/validate_kit.py` 退出码为 0。
- c. 解压目录内 `scripts/validate_kit.py --project-ready` **预期失败**（退出码 1 且输出含 `FILL_IN`）。这是正确行为而非缺陷：发布的是待填模板；若它"通过"了反而要报错。
- d. 解压目录内 `uv run python -m unittest discover -s tests` 退出码为 0。
- e. 解压目录内 `scripts/orchestrator.py init` 与 `scripts/orchestrator.py task list` 冒烟退出码为 0（`init` 会在临时目录创建 `.orchestration/`，属预期）。
- f. 非必要信息扫描零命中：对包内每个文本文件扫描个人路径与用户名、本仓库任务 ID、本仓库专有文档名与凭据痕迹；并断言包内不存在 `.orchestration/`、`release/`、`scripts/build_release.py`、`docs/` 等结构残留。命中即失败并打印文件与行号。凭据痕迹分两类：`ghp_`、`github_pat_`、`-----BEGIN`、`AKIA` 等精确子串；以及用精确形状正则匹配的 OpenAI 风格密钥——词边界 + `sk-` + 至少 16 位密钥字符（**不使用裸 `sk-` 子串**，否则会误命中 `task-id`、`risk-based`、`subtask-level` 等普通词，误拦正常发布）。此外，断言包内文本文件不含 CRLF（换行统一为 LF），保证构建对检出行尾不敏感；命中即失败并打印文件。
  - 扫描模式分层：**通用模式内置在脚本**（个人主目录、凭据形状等，任何克隆都适用）；**机器 / 本仓库相关模式放在 `.local/release-scan.json`**（`{"forbidden_patterns": [...]}`，逐条按精确子串匹配）。该文件缺失时跳过本地规则并打印 `extra scan patterns: none`；该文件永不入库、永不打包。
- g. 结束时打印摘要：包内文件数、zip 路径、zip 大小（字节）与 zip 的校验和（校验和用于复核：同一仓库状态下重建应得到同一值）。

自检失败时，脚本会**删除刚生成的、未通过自检的 zip**，并在失败信息中说明"已删除未通过自检的产物"（若删除失败则如实打印该产物路径），确保 `release/` 不会留下被误当发布物的半成品。

### 3.1 CI 与本标准的覆盖分工

`.github/workflows/ci.yml` 在 `pull_request`→`main`、`push`→`main` 与手动触发时，于 `ubuntu-latest` 的两个 Python 版本（3.12 / 3.13）上执行同一套自检：`uv run python scripts/build_release.py`。该步骤**失败即 job 失败**，没有 `continue-on-error`、`|| true` 或跳过开关；产物只写到 runner 的 `release/`（`.gitignore` 已忽略），不提交、不上传、不使用密钥。

- **两档都跑的理由**：自检 b、d 在解压目录里执行随包发布的 `validate_kit.py` 与 `unittest`，即真正检验"该 Python 版本拿到的包是否可用"；两档各证明一次，成本是本机数秒级重复，换来不设 `if:` 条件、不会出现某档静默跳过打包步骤。
- **CI 证明什么**：包能构建，且内置自检 a–f 通过 —— 覆盖"打包内容集合 / 包内结构校验 / 发布扫描 / 可复现归档"这类回归。
- **CI 不证明什么**：**不证明发布本身**。CI 不校验 `{YYYYMMDD}` 命名、不生成 GitHub Release、不写发布记录，也不替你判断"这一版是否该发"。发布仍按第 4 节由 Master 执行并逐项留证；CI 绿灯不能替代第 4 节的审查记录。

## 4. 发布流程

1. 在任务库登记发布任务（唯一 ID、单一目标、允许路径与验收）。
2. 从最新本地主分支创建独立分支 / Worktree；不在共享工作区直接构建。
3. 构建：运行 `uv run python scripts/build_release.py` 生成 `release/agentorch-{YYYYMMDD}.zip`。
4. 自检：确认脚本内置 a–f 全部通过并记录退出码；产物路径、字节数与校验和一并留证。CI 虽已在 PR 上跑过同一自检（见 3.1），发布时仍须在本分支上重跑并在发布记录里写入实际输出，不能用 CI 绿灯代替。
5. Master 独立审查（逐条对照本文件的自检清单与验收标准）。
6. 合并到本地主分支；合并后重新运行验证并记录结果。
7. 发布后清理本任务分支 / Worktree（独立记账，清理由此与"合并成功"分开记录）。

## 5. 版本变更（`VERSION.txt` 的 `Format version`）

- **1.4（当前）** 相对 1.3：
  - **设计目标权威迁到 `docs/PLAN.md`**：任务方向以 `docs/PLAN.md` 为准；`init` 在 `docs/PLAN.md` 缺失且无旧根 `PLAN.md` 时创建 `docs/` 并放入模板，发现旧根 `PLAN.md` 时不迁移、只提示 `git mv`；`validate_kit` 对残留根 `PLAN.md` 报错（fail-closed，防两个设计权威并存）。迁移步骤见仓库 `docs/UPGRADE-2026-10.md` 第 11 节。
  - **图片协作条款**：设计文档可配图（`docs/images/`，正文相对引用）；Agent 只按正文指引按需查看图片、禁止批量读取；图文双写；公开仓库截图脱敏。`docs/images/` 不随包发布。
  - **统一用 `uv` 运行 Python 脚本**：文档命令、模板验证命令与 CI 全部改为 `uv run python …` 前缀；CI 增加 setup-uv 步骤（`uv run` 会使用 PATH 上的解释器）。
  - **README 用户指引话术化**：启动 / 登记 / 派发 / 收口等说明改为中文自然语言话术（对 Agent 说），话术 → 命令 → 预期证据对照表保留在 README 3.0 节。
- **1.3** 相对 1.2：
  - **资源锁的载体字段**：任务载体新增具名资源锁字段——通用任务包 `declared_resources`（`<resource_id>:<mode>[:<ttl>]`）、`github` 登记块 `locked_resources` 与 `resource_lease_until`、`local` 任务库 `resources_json` 列。字段形状属载体契约，故格式版本升级；语义与冲突矩阵仍只在 `docs/design/RESOURCE-LOCKS.md`。
  - **`MANIFEST.json` 与 `check_drift.py`**：包内新增机器可读清单（自检 a 的校验对象），分类与清单生成下移到 `scripts/check_drift.py` 并由构建脚本导入，同时随包提供下游只读漂移诊断。
  - **CI 打包自检**：打包自检纳入 CI（见 3.1），并新增 `scripts/check_drift.py` 的 `py_compile` 语法检查；本文件与 README 的发布说明同步改为"包内容 == `REQUIRED` + `MANIFEST.json`"。
- **1.2**：包内新增 `MANIFEST.json` 与 `scripts/check_drift.py`（本次 1.3 记录将其约束补齐为可执行的清单校验）。

## 6. 声明

以后建 release 就按本文件执行：命名、包内容、自检与流程全部以本文件为准；任何偏离都必须先更新本文件并说明理由。
