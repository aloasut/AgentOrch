# Agent-Orchestration — 通用软件项目的启动与推进工具

> 本文件是入口。协作契约与安全规则以 [AGENTS.md](AGENTS.md) 和 [AGENT-ORCHESTRATION.md](AGENT-ORCHESTRATION.md) 为准；本文件不删除、不弱化其中任何规则。

## 1. 一句话定位

**把「需求 → 任务 → 执行 → 独立审查 → 合并 → 验证」固化成一条可执行、可核验的流程。**

它由两部分组成：一份与任务载体解耦的核心契约，以及两个可互换的底座（`local` / `github`）。核心契约规定谁可以做什么、任务如何流转、合并前必须过哪些门、什么才算证据；底座只决定任务状态写到哪里、证据从哪里取。配套的 Python 脚本负责登记任务、占用路径锁、做结构自检与打包，全部只用标准库。

目标是成为**通用软件项目的启动与推进工具**：因此自检覆盖必需文件、底座结构、治理概念与相对链接，配置允许按项目调整范围、验证命令、重试上限与私有目录，而不是把某一类项目的假设写死。

它主要解决四类问题：

- **多 Agent 协作失序**：不清楚谁在做哪个任务、改了哪些文件、两个任务是否改到同一路径。
- **状态丢失**：换会话、换机器或上下文被截断后，只能靠聊天记忆猜进度。
- **自批自合**：执行者自己宣布完成、自己批准、自己合并，审查门形同虚设。
- **证据不可核验**：只说“已完成”，不给出当前 head SHA 上的命令、输出与退出码；或用旧结论、CI 绿灯代替逐条验收。

**适用：**

- 一位操作者或一个小团队，用多个 Agent / 多个会话来推进一个软件项目。
- 希望每个任务都有明确的目标、允许路径、验收标准、依赖与证据。
- 愿意使用 Git 分支 / Worktree，并接受“执行者不自批、合并由 Master 决策”的约束。
- 需要一条从空目录启动、接入已有仓库、或从单机协作升级到平台协作的清晰路径。

**不适用：**

- 需要完整多人权限体系（角色管理、审批链、最小权限、账号隔离）的组织。
- 需要托管服务、SaaS 控制台、跨组织审计或合规认证的场景。
- 希望工具直接启动模型、写代码、跑测试或自动合并——本工具只管理治理状态，不替代 Agent 运行时与 Git 操作。
- 只需要一个看板或待办清单、不需要证据链与合并门的小项目。

## 2. 两种底座怎么选

两个底座共用同一份核心契约，角色权限、审查门、禁改路径、证据标准完全一致，**只有任务载体与证据来源不同**。底座由 [ORCHESTRATION-PROJECT.md](ORCHESTRATION-PROJECT.md) 的 `edition` 决定，取值只能是 `local` 或 `github`；缺失或非法时必须停止调度并报告，不得猜测或按默认值继续。本地 CLI 只维护 `local` 任务库：声明 `github` 时调度命令会被明确拒绝并给出下一步指引，而不是静默按 `local` 执行（支持矩阵见 6.2）。

| 维度 | `local`（[说明](editions/local/README.md)） | `github`（[说明](editions/github/README.md)） |
| --- | --- | --- |
| 形态 | 离线单机，不依赖托管平台 | 托管平台，Issue + Draft PR + CI |
| 任务载体 | SQLite 任务库 `.orchestration/state.sqlite3` | 每个任务一个 Issue，正文五节 |
| 锁 / 防冲突 | `task dispatch` 原子路径锁 | Issue 内 `ORCH-TASK-REGISTRY` 登记块 + 开放 PR 同文件检查 |
| 主要证据 | 本地命令输出、退出码、head SHA | CI 结果、PR 评论、head SHA |
| 协作范围 | 一位操作者、一台机器 | 多人、多地点，可异地接手 |
| 外部依赖 | Python 3 + Git，无需联网 | GitHub 仓库、平台权限、CI 工作流 |
| 适合 | 完全离线、单机、规模较小、内部项目 | 协作频繁、规模增长、需要公开可核验证据 |
| 主要代价 | 状态只在本机，无平台强制门 | 依赖平台可用性，公开内容必须脱敏 |

**选择判据：**

- 只有一台机器、可以完全离线、任务数量有限、审查记录只需内部可见：选 `local`。
- 需要异地接手、多人同时推进、需要平台强制的分支保护与必需检查、审查证据要对第三方可见：选 `github`。
- 拿不准时先 `local`；等协作需求明确后再迁移，不要一开始就为想象中的规模付出平台成本。

**什么时候该迁移：**

- 项目变大，任务数量、并行度或参与人数超出单机人工协调能力。
- 需要异地接手，或状态不能只留在某一台机器上。
- 需要公开、可独立核验的过程证据，或需要平台强制的合并门。

> 从 `local` 迁移到 `github` 是**授权决策**，不是偏离：多地协同开发时 GitHub 的优势明显，项目逐步变大后 `github` 底座更合适。

“先 `local` 后 `github`”是常见路径。迁移必须由项目所有者批准，**单向执行、一次性完成、禁止双写**：同一任务不能同时在任务库和 Issue 中维护状态。四步概览见 [AGENT-ORCHESTRATION.md 第 6 节](AGENT-ORCHESTRATION.md#6-底座切换)，落地路径见本文第 4 节。

并发不设固定数量：**按当前机器性能动态判断**，只要任务可并行且 CPU / 内存 / 磁盘 / 测试资源仍有余量，就可以并行；同一 Worktree 同一时刻只允许一个测试进程。

## 3. 快速开始（local）

以下序列从“空目录 + 一份套件”走到“第一条任务已派发”，并跑完结构自检与单元测试。命令在 Windows + Git Bash 下用 Python 3 实测通过；`python` 指当前环境的 Python 3 解释器。

### 3.1 放入套件

新建项目目录，把套件内容复制进去，保留 `scripts/`、`editions/`、`templates/` 等相对路径（示例源为已解压的分发包）：

```bash
mkdir my-project
cd my-project
cp -r /path/to/agentorch-YYYYMMDD/. .
```

若使用本仓库而不是分发包，复制时不要带上 `.git/`、`.worktrees/`、`.orchestration/` 与本机私有目录。随后编辑 `ORCHESTRATION-PROJECT.md`，至少填好 `edition: local`、允许 / 禁改路径和验证命令；分发包里的该文件是带 `FILL_IN` 的待填模板。

### 3.2 最小命令序列

```bash
python scripts/orchestrator.py init
python scripts/orchestrator.py config show
python scripts/orchestrator.py task add --id TASK-0001 --title "建立项目骨架" --paths README.md src/ --acceptance "有最小可运行入口" "测试命令退出码为 0"
python scripts/orchestrator.py task ready TASK-0001
python scripts/orchestrator.py task dispatch TASK-0001
python scripts/orchestrator.py task list
python scripts/validate_kit.py
python -m unittest discover -s tests
```

关键输出（为便于阅读，绝对路径以 `<项目根>` 代替，分隔符随平台变化、示例为 Windows 写法；路径末尾的 `/` 会被规范化为 `src`）：

```text
$ python scripts/orchestrator.py init
Initialized local task registry: <项目根>\.orchestration\state.sqlite3
Review-fix retry cap: 3 (edit key "retry_cap" in <项目根>\.orchestration\config.json to change it)
Local task registry only: the edition is read from <项目根>\ORCHESTRATION-PROJECT.md, not from this config.
Back up .orchestration/ with your project backups.

$ python scripts/orchestrator.py config show
Config file: <项目根>\.orchestration\config.json
  retry_cap  = 3          (source: config.json)
  local_dir  = .local     (source: config.json)
  edition    = local      (source: ORCHESTRATION-PROJECT.md)
Edition is selected only by `edition` in <项目根>\ORCHESTRATION-PROJECT.md; config.json holds local CLI runtime parameters (retry_cap, local_dir) and never selects an edition.
Edit .orchestration/config.json to change retry_cap or local_dir; invalid values there fall back to defaults.

$ python scripts/orchestrator.py task add --id TASK-0001 --title "建立项目骨架" --paths README.md src/ --acceptance "有最小可运行入口" "测试命令退出码为 0"
TASK-0001: created in PLANNED

$ python scripts/orchestrator.py task ready TASK-0001
TASK-0001: READY

$ python scripts/orchestrator.py task dispatch TASK-0001
TASK-0001: DISPATCHED; locks acquired for README.md, src
Now pass the self-contained task packet to a real Execution Agent. This command does not launch agents.

$ python scripts/orchestrator.py task list
TASK-0001	DISPATCHED	建立项目骨架
  paths: README.md, src
  locks: README.md, src
  retries: 0

$ python scripts/validate_kit.py
Kit validation passed (38 required files checked; editions local/github share 7 files, github adds 3 templates).

$ python -m unittest discover -s tests
Ran 63 tests in 7.936s
OK
```

说明：

- `init` 创建 `.orchestration/state.sqlite3` 与 `.orchestration/config.json`，并把 `.orchestration/` 写入当前克隆的 `.git/info/exclude`（若存在 Git），不会覆盖项目的 `.gitignore`。
- `dispatch` 只登记状态并占用路径锁，**不会启动 Agent**。拿到锁后，把自包含任务包交给真实执行实例；没有真实 spawn 能力时，由操作者另开会话执行。
- 单元测试会大量打印临时任务库日志，属正常现象；退出码为 0 即通过。
- 冒烟完成后可取消这条示例任务并释放锁：`python scripts/orchestrator.py task status TASK-0001 CANCELED --note "快速开始冒烟结束"`。

## 4. 三条落地路径

### 路径一：空目录启动新项目

目标：从一句想法走到项目章程、首批任务与第一个可运行切片。

1. 按第 3 节把套件放入空目录，`ORCHESTRATION-PROJECT.md` 填 `edition: local`。
2. 运行 `python scripts/orchestrator.py init` 与 `python scripts/orchestrator.py task list`，确认任务库可用且为空。
3. 在 Master Agent 会话中加载 [editions/local/START-MASTER-NEW-PROJECT.md](editions/local/START-MASTER-NEW-PROJECT.md)，按提示词澄清目标、产出章程、拆出 1–3 个最小任务。
4. 若想法本身还很模糊，先走 [prompts/START-CHARTER.md](prompts/START-CHARTER.md) 的章程引导流程，再进入任务拆解。

### 路径二：接入已有仓库

目标：在不破坏既有规则的前提下接入套件，恢复真实进度，再继续推进。

1. 把套件复制进现有仓库根目录；**已有 `AGENTS.md` 时先人工合并，不能盲目覆盖**。
2. 填写 `ORCHESTRATION-PROJECT.md`：底座、主分支、允许 / 禁改路径、验证命令、并发策略。
3. 运行：

   ```bash
   python scripts/orchestrator.py init
   python scripts/orchestrator.py task list
   python scripts/validate_kit.py
   ```

4. 在 Master Agent 会话中加载 [editions/local/START-MASTER-EXISTING-PROJECT.md](editions/local/START-MASTER-EXISTING-PROJECT.md)。该提示词会要求先读 Git 状态与任务库，再拆任务与派发。

### 路径三：从 `local` 迁移到 `github`

目标：把任务状态从本机任务库迁到 Issue / PR / CI，切换后只保留一个事实来源。

入口：[AGENT-ORCHESTRATION.md 第 6 节「底座切换」](AGENT-ORCHESTRATION.md#6-底座切换)。四步概览：

1. **冻结写入并导出 Issue**：停止 `local` 派发与状态变更，记录切换点的主分支 SHA 与任务库备份位置；每个未完成任务按 [ISSUE-TEMPLATE.md](editions/github/ISSUE-TEMPLATE.md) 的五节导出一个 Issue，已完成任务只归档摘要。
2. **建立平台保护与 CI**：配置默认分支保护、必需检查与 PR 模板，使合并门由平台强制执行。
3. **登记块接管锁**：开工前在 Issue 写 `ORCH-TASK-REGISTRY` 登记块，并检查所有开放 PR 的变更文件是否与 `locked_paths` 相交；两者都通过才算取得锁。
4. **切换点一次性完成**：状态映射、证据迁移、合并后主分支重验一次做完；迁移后所有状态只写入 Issue / PR，任务库转为只读归档。

迁移完成后，按 `github` 底座的启动提示词继续：[START-MASTER-NEW-PROJECT.md](editions/github/START-MASTER-NEW-PROJECT.md) 或 [START-MASTER-EXISTING-PROJECT.md](editions/github/START-MASTER-EXISTING-PROJECT.md)。迁移是单向的，本套件不提供自动回退；确需回退时由项目所有者单独立项。

## 5. 目录结构

```text
.
├── AGENTS.md                          # 核心契约：角色、权限、Git 纪律、安全（唯一权威）
├── AGENT-ORCHESTRATION.md             # 核心编排：状态机、G1–G6、C1–C4、底座切换
├── AGENT-ORCHESTRATION-ACCEPTANCE.md  # 通用验收程序
├── AGENT-BOOTSTRAP.md                 # 会话入口：判定底座、恢复状态、自动路由
├── ORCHESTRATION-PROJECT.md           # 每个项目自己的配置（edition 在这里）
├── README.md                          # 本文件：入口与使用说明
├── VERSION.txt                        # 套件名与 Format version
├── LICENSE.txt
├── editions/
│   ├── local/                         # local 增量：SQLite 命令、路径锁、启动提示词
│   └── github/                        # github 增量：Issue / PR 模板、登记块、启动提示词
├── prompts/                           # 两底座共享提示词（章程、Reviewer）
├── templates/                         # 任务包、计划、设计、审查清单、项目配置模板
├── scripts/
│   ├── orchestrator.py                # local 任务库与原子路径锁 CLI
│   ├── validate_kit.py                # 结构 / 概念 / 链接自检，同时是发布清单
│   └── build_release.py               # 发布构建（仅仓库内，不随包发布）
├── tests/                             # orchestrator 的单元测试
├── .github/workflows/ci.yml           # PR / main 推送时跑三条登记检查（github 底座 G4 证据；仅本仓库，不随包发布）
├── release/README.md                  # 发布标准与发布清单（产物不入库）
├── docs/                              # 本仓库自己的章程与决策记录（不随包发布）
└── .local/                            # 本机私有文件（除说明文件外不入库）
```

**核心只有一份，底座只做增量。** `AGENTS.md` 与 `AGENT-ORCHESTRATION.md` 定义与底座无关的契约；`editions/local/` 与 `editions/github/` 只能细化命令、模板和载体操作，不得复制或改写出另一套核心条款。底座手册与核心契约冲突时，以核心契约为准。

## 6. 配置

### 6.1 项目配置：`ORCHESTRATION-PROJECT.md`

每个项目必须填写这份文件，它决定项目怎么被调度：

| 字段 | 作用 |
| --- | --- |
| `edition` | 底座的**唯一权威来源**，只能 `local` 或 `github`，且只写取值、不加说明文字；缺失、为空、非法字符串或类型错误时阻断调度，并报出实际值与修复位置（文件 + 键名） |
| 允许改动路径 / 永远禁止改动路径 | 任务默认范围与硬边界；任务只能进一步收窄 |
| 验证命令 | 审查门 G4 要求的测试、静态检查、构建命令；必须可真实执行 |
| 并发策略 | 不写固定数字，按机器余量动态判断 |
| 本地工作流 | 分支命名、Worktree 根目录、审查修复上限、备份节奏 |
| 风险与人工批准 | 数据删除 / 迁移、权限或安全变化、外部服务、不可逆动作 |

分发包里的这份文件是待填模板；也可以参考 [templates/ORCHESTRATION-PROJECT.template.md](templates/ORCHESTRATION-PROJECT.template.md)。

### 6.2 运行时配置：`.orchestration/config.json`

由 `python scripts/orchestrator.py init` 创建，**只描述本地 CLI 的运行参数**；它不决定底座，也不存在“缺省底座”。底座只看 6.1 的 `edition`。

| 键 | 允许值 / 默认 | 作用 |
| --- | --- | --- |
| `retry_cap` | 整数 ≥ 1，默认 `3` | 审查—修复往返上限；达到上限仍未通过则转 `BLOCKED` |
| `local_dir` | 非空字符串，默认 `.local` | 本机私有目录的位置 |

**非法值的处理分两类，不要混淆**：

- `retry_cap` / `local_dir`：文件缺失、键缺失、类型错误、取值非法或 JSON 损坏时**静默回落到内置默认**，既有本地库行为不变。
- `edition`：只在 `ORCHESTRATION-PROJECT.md` 中读取。缺失、为空、非法字符串（如 `GITHUB`、`cloud`）、类型错误（如 `1`、`true`）、重复声明或文件不可读时**阻断调度**，诊断给出实际值与修复位置（文件 + 键名）。`config.json` 里残留的 `edition` 键只作为历史记录，`config show` 会标注 `legacy key is ignored`，不参与路由。

查看每个键的生效值与来源：

```bash
python scripts/orchestrator.py config show
```

`source` 为 `config.json` 表示来自运行时文件，为 `default` 表示回落到内置默认；`edition` 的来源固定是 `ORCHESTRATION-PROJECT.md`。示例（合法覆盖 + 合法 `local` 声明）：

```text
Config file: <项目根>\.orchestration\config.json
  retry_cap  = 5          (source: config.json)
  local_dir  = .private   (source: config.json)
  edition    = local      (source: ORCHESTRATION-PROJECT.md)
Edition is selected only by `edition` in <项目根>\ORCHESTRATION-PROJECT.md; config.json holds local CLI runtime parameters (retry_cap, local_dir) and never selects an edition.
Edit .orchestration/config.json to change retry_cap or local_dir; invalid values there fall back to defaults.
```

`edition` 缺失或非法时，`config show` 仍打印运行参数，同时把诊断写到 stderr 并以退出码 1 结束。

#### 底座与命令支持矩阵

| 命令 | `local` | `github` | `edition` 缺失 / 非法 |
| --- | --- | --- | --- |
| `init` | 可用 | 可用（只建本地库，不选底座） | 可用 |
| `backup` | 可用 | 可用 | 可用 |
| `config show` | 可用，退出码 0 | 可用，退出码 0 | 打印诊断，退出码 1 |
| `task list` / `task show` | 可用 | 可用（只读归档） | 可用（只读） |
| `task add` / `ready` / `dispatch` / `status` / `workspace` / `amend` / `unlock` | 可用 | 拒绝，并给出 Issue / PR 指引 | 拒绝，并给出实际值与修复位置 |

`github` 底座的调度由 Issue / PR 承载：新建任务按 [editions/github/ISSUE-TEMPLATE.md](editions/github/ISSUE-TEMPLATE.md) 写 Issue，执行按 [editions/github/START-EXECUTION.md](editions/github/START-EXECUTION.md) 推进。本地 CLI **不**声称支持 github 调度，也不会把状态写进本地库。

### 6.3 私有目录：`.local/`

隐私文件统一放在 `.local/`，**除目录说明外永不入库、永不打包**：

- `.env` 等环境变量与凭据；
- 机器信息（CPU、内存、磁盘、实测可承载并发、解释器路径等本机事实）；
- 发布扫描规则（发布构建使用的额外禁用词）。

`.gitignore` 用 `.local/*` 忽略全部内容，只保留 `.local/README.md` 作为目录说明；该说明文件本身不得写任何个人信息、凭据或主机事实。分发包按 `validate_kit.py` 的文件清单打包，`.local/` 不在清单内，因此不会被发布。若修改 `local_dir`，必须同步更新 `.gitignore`，否则私有文件可能被提交。

### 6.4 并发策略

不设固定并发数量。派发前观察 CPU、内存、磁盘与测试资源争用：只要任务之间依赖已满足、路径锁不冲突，且机器仍有余量，就可以并行；资源紧张时串行。同一 Worktree 同一时刻只允许一个测试进程，也不要让两个执行实例共享可写工作区。“本机实测可承载并发”只作为记录，不作为规则常量。

## 7. 自检

套件自带两层自检：结构自检保证文件与文档没有腐化，单元测试保证任务库与锁的行为不变。

```bash
python scripts/validate_kit.py
python scripts/validate_kit.py --project-ready
python -m unittest discover -s tests
python -m py_compile scripts/orchestrator.py scripts/validate_kit.py
```

`validate_kit.py` 检查：

- **37 项必需文件**是否齐全（`REQUIRED` 列表同时是发布包清单，只有一份来源）。
- **两底座结构是否一致**：`editions/local` 与 `editions/github` 共享 7 个文件，`github` 额外提供 3 个模板；任一侧缺失或出现多余文件都会失败。
- **治理概念是否真实存在**：核心编排文档必须出现 `PR_OPEN`、合并门 G1–G6、运行时能力契约 C1–C4；文档整体必须出现主要状态名。
- **`edition` 是否合法**：`ORCHESTRATION-PROJECT.md` 必须有该键，且值为 `local` 或 `github`。
- **相对链接是否可解析**：扫描所有 Markdown 链接，断链即失败（外部 URL 与锚点除外）。

`--project-ready` 的含义：在项目配置填完之后追加检查，只要 `ORCHESTRATION-PROJECT.md` 里仍有 `FILL_IN` 占位符就以退出码 1 失败。发布包里的 `ORCHESTRATION-PROJECT.md` 故意保持待填模板，因此**发布自检中该命令预期失败**；若它通过了，反而说明模板没有被正确替换。

`unittest` 覆盖状态机、依赖、路径锁、重试上限、head SHA 与 merge SHA，以及 edition 的权威来源与 fail-closed 行为；当前 63 个用例。`py_compile` 只做零依赖语法检查，不引入任何第三方工具。

### 7.1 CI（`github` 底座）

仓库自带一条 GitHub Actions 工作流 `.github/workflows/ci.yml`（仅本仓库使用，不随发行包发布），把上面三条登记检查放到平台上执行：

- **触发**：`pull_request` 目标 `main`、`push` 到 `main`、以及手动 `workflow_dispatch`。
- **环境**：`ubuntu-latest`，Python 版本矩阵 `3.12` / `3.13`（两个版本都跑，任一失败即整体失败）。
- **步骤**：只有三条登记检查，按顺序执行且不跳过失败步骤 —— `python scripts/validate_kit.py`、`python -m unittest discover -s tests`、`python -m py_compile scripts/orchestrator.py scripts/validate_kit.py`。
- **边界**：`permissions: contents: read`，不使用 `pull_request_target`，不引入第三方依赖、密钥或 `pip install`。

**证据地位**：`github` 底座下，G4 以**当前 head SHA** 上的 CI 运行全绿为准 —— 本地三条命令仍是可复现的补充证据，不能替代 CI；反过来，CI 绿灯也只覆盖这三条命令，不能代替 G1 的逐条验收。head 变化后旧 head 的绿灯失效，必须在新 head 上重新运行。

**查看方式**：

- PR 页面的 **Checks** 区域（或提交旁的绿勾 / 红叉）展开即见各矩阵任务与失败步骤日志；
- 命令行：`gh pr checks <PR 编号>` 查看当前 head 的检查状态，`gh pr checks <PR 编号> --watch` 等待结果；
- Actions 页面（`https://github.com/<owner>/<repo>/actions/workflows/ci.yml`）可查历史运行记录；写证据矩阵时记录运行 URL 与 head SHA。

发布前的完整自检（构建内置、无跳过开关）见 `release/README.md`。

## 8. 发布

- **构建**：`python scripts/build_release.py` 产出 `release/agentorch-{YYYYMMDD}.zip`，包内文件集合直接取自 `validate_kit.py` 的 `REQUIRED` 列表。
- **产物不入库、自检强制**：`release/*.zip` 已被忽略；构建后自动执行 a–f 自检，失败会删除未通过自检的产物，没有跳过开关。
- **可复现**：归档时间戳固定、文本文件按 LF 归一后打包；同一仓库状态重建应得到同一 SHA256。

命名、包内容、自检清单、发布流程与发布清单以 `release/README.md` 为准，本节只保留三条要点。

## 9. 版本与兼容

- [VERSION.txt](VERSION.txt) 记录套件名、支持底座与 **Format version**（当前 `1.1`）；格式变更时同步更新模板与校验清单。
- `1.1` 相对 `1.0` 的变更要点：
  - **双底座**：`Edition: offline-single-user` 改为 `Editions: local, github`，同一套核心契约下分 `local`（纯本地）与 `github`（多人协作）两种底座，选择判据见第 2 节。
  - **`.local` 隐私层**：机器信息、凭据与发布扫描规则统一放 `.local/`，除目录说明外永不入库、永不打包（见 6.3 节）。
  - **按机器余量的并发策略**：不再固定并发数量，派发前按 CPU、内存、磁盘与测试资源余量决定并行度（见 6.4 节）。
  - **配置自省**：`python scripts/orchestrator.py config show` 可查看每个配置键的生效值与来源，便于定位缺省值与项目覆盖。
- 纯 **Python 3 标准库**，**零第三方依赖**；不需要数据库服务、包管理器或构建步骤。
- 已在 **Windows + Git Bash** 环境用 Python 3 验证；三条登记检查另由 CI 在 `ubuntu-latest` + Python 3.12/3.13 上运行（见 7.1）。其他操作系统、其他 shell 与其余命令**未验证**，命令中的引号与路径写法可能需要调整。
- `orchestrator.py` 只管理本地任务状态与路径锁，不启动模型、不写代码、不运行项目测试、不自动合并 Git 分支；这些动作由 Agent 按提示词执行，合并由 Master 决策。
- 若运行时无法真实完成 spawn / wait / collect（C1–C4 未全部通过），必须降级为多会话人工交接，不得声称已派发。

## 10. 治理文档导航

| 文档 | 什么时候读 | 读完后做什么 |
| --- | --- | --- |
| [AGENTS.md](AGENTS.md) | 每次接手项目、写代码或做审查之前 | 确认角色权限、Git 纪律、证据标准与安全边界 |
| [AGENT-ORCHESTRATION.md](AGENT-ORCHESTRATION.md) | 派发任务、改状态、审查合并、迁移底座之前 | 对照状态机、G1–G6、C1–C4 执行 |
| [AGENT-BOOTSTRAP.md](AGENT-BOOTSTRAP.md) | 每次会话开始时 | 判定底座、恢复真实状态、路由到对应流程 |
| [ORCHESTRATION-PROJECT.md](ORCHESTRATION-PROJECT.md) | 初始化项目或调整范围 / 验证命令时 | 填好 `edition`、路径边界、验证命令与并发策略 |
| [editions/local/MASTER.md](editions/local/MASTER.md) / [editions/github/MASTER.md](editions/github/MASTER.md) | 当前底座的日常操作 | 按底座手册创建、派发、审查、合并任务 |
| [editions/github/ISSUE-TEMPLATE.md](editions/github/ISSUE-TEMPLATE.md) | 在 `github` 底座创建任务单时 | 按五节写 Issue，缺一节不得进入 `READY` |
| [prompts/START-CHARTER.md](prompts/START-CHARTER.md) | 想法模糊、涉及新方向 / 多文件 / 新依赖 / 不可逆操作时 | 先澄清并签署项目章程，再拆任务 |
| `release/README.md` | 准备发布分发包之前 | 按发布标准构建、自检、登记清单 |
