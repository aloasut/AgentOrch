# AGENT-ORCHESTRATION.md — 核心编排细则（Edition-Neutral）

本文件定义两个底座共用的编排契约：状态机、任务锁、合并门、运行时能力探测与切换规则。任务载体和证据来源由 `ORCHESTRATION-PROJECT.md` 的 `edition` 决定：`local` 使用 SQLite 任务库与原子路径锁，`github` 使用 Issue 任务单、Draft PR 与 CI。若某项能力依赖运行时支持而当前环境并不具备，必须降级并记录依据，不得假装执行。

## 1. 适用方式

- 核心条款只有这一份。底座手册（`editions/<edition>/MASTER.md` 与对应提示词）只能细化命令和载体操作，**不得复制或改写出另一套核心条款**；发现底座手册与本文件冲突时，以本文件为准并登记任务修正。
- 状态、门禁、审批与合并的语义在两个底座完全一致，差异只体现在“写到哪里、用什么命令查”。
- 任何一项能力或检查未实际执行时，状态不得前进；“未知”一律按未完成处理。

## 2. 任务状态机

```text
PLANNED → READY → DISPATCHED → IN_PROGRESS → [PR_OPEN] → REVIEW_READY → MASTER_REVIEW → APPROVED → MERGED → VERIFIED
非成功状态：BLOCKED / NEEDS_HUMAN_DECISION / FAILED / CANCELED
```

- `PLANNED`：任务草稿已登记，但依赖或验收可能尚未齐备。
- `READY`：目标、路径、验收和依赖均明确；所有依赖任务为 `VERIFIED`。
- `DISPATCHED`：已取得活动任务锁（`local`：完整路径锁；`github`：Issue 登记块 + 开放 PR 冲突检查），任务包已交给真实执行实例。
- `IN_PROGRESS`：执行实例已开始；应记录分支 / Worktree。
- **`PR_OPEN`**：Draft PR 已创建并在 Issue 中登记。**仅 github 底座使用**；`local` 底座由 `IN_PROGRESS` 直接进入 `REVIEW_READY`，不存在该状态。
- `REVIEW_READY`：实现者交回 Diff、head SHA、验证命令 / 输出和剩余风险；`github` 底座要求 PR 已转为 Ready for review 且 CI 在当前 head 全绿。
- `MASTER_REVIEW`：Master 独立检查任务、变更范围、证据和风险。
- `APPROVED`：验收全部通过；批准必须绑定精确 head SHA（`github` 为 PR 最新 commit）。
- `MERGED`：已确认合并到主分支。远端或本地分支清理状态应单独记录，不可混为合并成功的判据。
- `VERIFIED`：在合并后的主分支上完成必要验证，记录命令 / 退出码 / 结果。完成后释放活动任务锁。
- `BLOCKED`：外部依赖、文件冲突或环境问题暂时阻止推进；记录恢复条件。
- `NEEDS_HUMAN_DECISION`：需项目所有者选择或授权；必须记录具体问题与选项。
- `FAILED`：执行实例失败、超时、取消或产物不可用；**状态未知一律视为未完成**。
- `CANCELED`：项目所有者或 Master 明确取消；记录原因后释放锁。

### 2.1 两底座状态对照

| 状态 | `local` 载体 | `github` 载体 |
|------|--------------|---------------|
| `PLANNED` / `READY` | 任务库记录 + 依赖检查 | Issue（正文五节 + label） |
| `DISPATCHED` | `task dispatch` 原子取得全部路径锁 | Issue 内 `ORCH-TASK-REGISTRY` 块 + 开放 PR 同文件检查 |
| `IN_PROGRESS` | 分支 / Worktree 记录 | 分支已推送；Draft PR 尚未创建 |
| `PR_OPEN` | 不使用 | Draft PR 已创建并回链 Issue |
| `REVIEW_READY` | 交回 head SHA 与本地验证输出 | PR 转 Ready；CI 在当前 head 全绿 |
| `MASTER_REVIEW` | Master 查看 Diff 与日志 | Master 查看 PR Diff、CI 与评论 |
| `APPROVED` | 绑定 head SHA | 绑定 PR 最新 commit SHA |
| `MERGED` | `git merge --no-ff`（按项目配置） | 平台合并（策略按项目配置） |
| `VERIFIED` | 主分支重跑检查 | 主分支重跑检查（不只看 CI） |

状态改变由底座载体记录：`local` 通过 `scripts/orchestrator.py` 写入任务库，不要手工编辑 SQLite；`github` 通过 Issue / PR 状态转换与评论记录。载体提供的是治理记账，不会代替运行时真正派发或运行测试。

## 3. 派发、活动任务锁与依赖

### 3.1 取得活动任务锁

`local`：

1. 任务先进入 `READY`，然后运行 `python scripts/orchestrator.py task dispatch <ID>`。CLI 使用 SQLite `BEGIN IMMEDIATE` 原子检查锁并登记 `DISPATCHED`。
2. 锁范围由任务允许路径确定；比较采用路径相同或父子路径重叠的方式。例如 `src/` 与 `src/core.py` 冲突，`src/a.py` 与 `src/b.py` 不冲突。
3. 只有当全部路径可锁定时才一次性取得全部锁；冲突则整个派发失败，不允许半锁状态。
4. 任务处于活动状态时，不得修改锁定路径集合。确需扩大范围时，先阻塞任务、记录理由、检查新路径冲突并更新登记。
5. 仅进入 `VERIFIED` 或 `CANCELED` 自动释放锁。失败、超时、未知状态、审查退回或单纯删除 Worktree 都不自动释放。异常清理需运行显式 `task unlock` 并记录理由；强制解锁可能允许冲突，应先确认原任务已停止。

`github`：

1. 任务 `READY` 后，在 Issue 内写入 `ORCH-TASK-REGISTRY` 登记块（字段见 `editions/github/ACTIVE-TASK-REGISTRY.md`），声明 `status`、`mode`、`locked_paths`、`branch`、`pr`、`runner`、时间戳与 `head_sha`。
2. 写入登记块前必须列出所有开放 PR 及其变更文件，检查是否与本次 `locked_paths` 相交；相交则整个派发失败，不得“先开工再协调”。
3. 登记块写入成功且无路径冲突，才可把任务包交给执行实例。
4. 活动期间不得悄悄扩大 `locked_paths`；确需扩大时先更新登记块并在 Issue 评论说明，再重新做冲突检查。
5. 只有任务进入 `VERIFIED` 或 `CANCELED` 才把登记块标记为释放；`FAILED` 与状态未知保持锁定并写 `blocked_reason`。
6. 每次启动或恢复 Master 时，先读取 Issue 登记块与开放 PR 列表，再核对 `git status`、主分支与分支 head；不要从聊天记忆重建。

### 3.2 依赖与并行

- 依赖应构成有向无环图。依赖必须达到 `VERIFIED`，不能仅因为代码已提交、已合并或 PR 已批准就派发下游任务。
- 同一文件或目录前缀冲突的任务串行；不冲突且无依赖的任务可以并行。
- 并行度按机器余量决定，不写固定数字。派发前观察 CPU / 内存 / 磁盘 / 测试资源争用，有余量即可并行；同一 Worktree 同一时刻只允许一个测试进程。
- 不要让两个实例编辑同一个 Worktree；`github` 底座也不允许两个 PR 同时改同一锁定路径。
- 如果运行时不能真实 spawn / wait / collect，Master 产出任务包，由同一位操作者在另一个会话启动执行实例；Master 不声称它已启动。能力判定见第 5 节。

### 3.3 具名资源锁（契约见 `docs/design/RESOURCE-LOCKS.md`）

3.1 的路径锁只判定“是否改同一批文件”，无法表达测试数据库、共享构建环境等具名资源冲突。具名资源锁的语义（数据模型、冲突矩阵、原子集合获取、租约与恢复、底座能力边界、故障场景）**只在 `docs/design/RESOURCE-LOCKS.md` 定义**，本节不重述、不改写；本文件的状态机、门禁与锁取得条件（3.1）保持不变。

- 资源锁是路径锁之外的**增量**判定：两者都通过才可派发；未声明资源的任务行为不变。
- `local` 可声明“同一数据库文件范围内的原子互斥”；`github` 只能登记协作性占用并做冲突检查，**不得宣称原子锁**（依据见契约第 7 节）。
- 只有 `VERIFIED` / `CANCELED` 自动释放；`FAILED`、`BLOCKED` 与状态未知保持占用，过期不等于释放。
- 契约改动必须另开 Issue 重新冻结，实现任务不得在实现 PR 中顺手修改语义。

操作入口（判定语义只在契约里，本节只列命令与配置键）：

| 目的 | 命令 | 前置条件 |
|------|------|----------|
| 声明资源集合 | `task add ... --resources <id:mode>[:<ttl>] ...`（可选） | 资源 ID 已按契约 §2.1 规范化；不声明即不参与 |
| 派发并取得整批锁 | `task dispatch <ID> --resource <id:mode>[:<ttl>] --holder <ID> --evidence <ref>` | 任务 `READY`；`.orchestration/config.json` 显式配置租约 |
| 查看锁与阻塞 | `task resources [--resource <id>] [--all]`、`task list`、`task show <ID>` | 只读；`github` 底座只列出已存在记录 |
| 续租自己的锁 | `task renew <ID> --holder <ID> [--reason ...]` | 只有持有者可续租；已强制解锁的任务得到 `LOCK_NOT_HELD` |
| 回收过期锁 | `task reclaim <ID> --resource <id> --reason ... --evidence ...` | 已 `EXPIRED`、冷却期已过、附终局证据 |
| 单资源释放 / 强制解锁 | `task unlock <ID> --resource <id> --reason ... [--force --authorized-by <ID>]` | 强制解锁必须有理由；非终局任务还需授权人 |
| 跨会话重建事实 | `task reconcile [--reason ...] [--evidence ...]` | 只读锁表与审计事件；缺证据者进入隔离 |

配置键（`.orchestration/config.json`，无内置默认、只在声明了资源的任务上读取）：`resource_lease_ttl`、`resource_reclaim_grace`。缺失或非法时派发被拒绝，并指名要修的键。

## 4. 合并门 G1–G6

`MASTER_REVIEW` 必须逐门检查。任一门的结论不是“通过”，就退回 `IN_PROGRESS` 或 `BLOCKED`，写明具体缺口；不得用其他门的通过来抵消。

| 门 | 要求 | `local` 证据 | `github` 证据 | 原审查检查项 |
|----|------|--------------|---------------|--------------|
| **G1 验收逐条通过** | 每条验收标准都有对应证据，部分通过不算通过 | 任务记录 + 命令输出 | Issue 验收清单 + PR 评论逐条结论 | 1 |
| **G2 范围合规** | 实际变更路径全部属于允许路径，无未授权文件，无夹带重构 | `git diff --name-only` + `git status --short` | PR changed files + 任务允许路径 | 2、3 |
| **G3 基线最新且可合并** | 分支基于最新主分支；无冲突；合并预演可完成 | 主分支 SHA + 本地 merge 预演结果 | PR 为 `MERGEABLE` 且 base 为最新主分支 | 3 |
| **G4 必需检查全绿** | 配置要求的检查在**当前 head SHA** 上全部通过 | 配置的测试 / lint / typecheck / build 退出码为 0 | CI 工作流在当前 head SHA 全绿 | 4 |
| **G5 证据真实可复现** | 命令、输出、退出码与 head SHA 一致；失败测试未被删除、跳过或弱化 | 本地日志 + head SHA | CI 日志 + PR 评论 + head SHA | 5、7 |
| **G6 风险已处置** | 新依赖、迁移、权限 / 安全变化、未实现行为与回退方案已登记或升级为 `NEEDS_HUMAN_DECISION` | 任务记录的风险节 | PR 风险节 + Issue 决策记录 | 6 |

门的执行细则：

- **G1**：Master 不采信“已完成”的自述，也不把 CI 绿灯当作验收通过；逐条对照验收标准给出依据。逐条依据的记账格式见 4.1 节：验收标准未映射到任何 evidence item 时按未通过处理。
- **G3**：基线落后时必须先 rebase / merge 最新主分支并重新验证；不得在过期基线上批准。
- **G4**：检查运行在哪个 SHA 必须可定位。`github` 底座只承认当前 head 的 CI 结果；重跑旧 commit 或本地通过不能替代。`local` 底座不得把“配置里写了命令”当作“命令已通过”。
- **G5**：证据不全会直接退回。任何“历史运行过”的说法都要求能定位到当前 head；无法复现即视为未验证。
- **G6**：出现数据删除 / 迁移、权限或安全模型变化、新增外部服务、不可逆动作、重大架构取舍、产品语义歧义时，必须先记录选项与影响，进入 `NEEDS_HUMAN_DECISION`，不得由执行者或 Master 单方面决定。

门禁之后：

- `APPROVED` 必须带当前完整 commit SHA。工作树或提交头有任何变化，批准立即失效，需重新审查。
- 只有 Master 执行合并（`local` 例如 `git merge --no-ff <branch>`，`github` 例如平台合并按钮 / `gh pr merge`；具体策略由项目配置决定）。执行者不能自批自合。
- 合并前备份或确认可恢复；遇到冲突不自动覆盖他人 / 主分支内容。
- 合并后运行 `ORCHESTRATION-PROJECT.md` 指定的验证命令，保存日志与退出码；全部通过后转 `VERIFIED`。
- 合并成功与分支清理分开记账。清理失败不能触发重复合并。
- 默认最多 3 轮审查—修复往返；达到上限仍未通过 → `BLOCKED`，由项目所有者决定拆分、扩大范围或取消。

### 4.1 验收证据矩阵（Evidence Matrix）

G1 的“逐条验收”以**证据矩阵**记账：每条验收标准（AC）至少映射一条 evidence item，同一 AC 可以有多条（不同方法、不同环境、不同负向场景）。

字段名与判定规则只在本节定义。`templates/TASK-PACKET.md`、`editions/github/ISSUE-TEMPLATE.md` 与底座手册只引用这些字段名，并说明证据存放在哪里、如何取回，**不得另写一套定义或改写取值含义**。两个底座的字段完全相同，差异只在载体：`local` 写入任务记录 / 证据文件，`github` 写入 Issue 验收清单与 PR 评论。

**证据条目（evidence item）字段** — 唯一权威定义：

| 字段 | 必填 | 含义 | 取值 / 规则 |
|------|------|------|-------------|
| `ac_id` | 是 | 该条证据证明的验收标准 | 与任务包 / Issue 中的编号一致（`AC-1`、`AC-2`…）；不得指向不存在的 AC |
| `method` | 是 | 取证方法 | 可执行命令（含参数与范围）、测试用例名、人工检查步骤 |
| `expected` | 是 | 期望结果 | 与验收标准一致、可判定的描述或期望输出 |
| `actual` | 是 | 实际观察到的结果 | 真实输出摘要 / 实测值，不得写“应该通过” |
| `status` | 是 | 该条证据的判定 | `PASS` / `FAIL` / `NOT_RUN` / `BLOCKED` / `NOT_APPLICABLE`，只允许这五个值 |
| `environment` | 是 | 证据的运行环境 | 操作系统、运行时及版本、底座、分支 / Worktree 等可复现信息 |
| `commit_sha` | 是 | 证据所属的完整 commit SHA | 必须等于矩阵声明的 head SHA；`NOT_APPLICABLE` 可写 `(none)` |
| `evidence_ref` | 是 | 证据的可定位来源 | PR / Issue 评论、日志文件、Diff 路径、任务记录条目 |
| `notes` | 是 | 备注与限制 | 无补充写 `(none)`；`NOT_APPLICABLE` 时必须写不适用的理由 |

`status` 的语义：

- `PASS`：实测结果与 `expected` 一致，且属于矩阵声明的 head SHA。
- `FAIL`：实测结果与 `expected` 不一致。
- `NOT_RUN`：本次没有执行该检查；**不得折算为通过**。`actual` 写明“未执行”的事实，`commit_sha` 写判定所依据的 head。
- `BLOCKED`：本应执行但被外部依赖或环境阻塞；**不得折算为通过**，原因写进 `notes`。
- `NOT_APPLICABLE`：该 AC 对本任务确实不适用；必须在 `notes` 写明理由，且不参与“已通过”的结论。

判定规则（G1 的执行细则）：

1. 每条 AC 至少一条 evidence item；没有任何证据的 AC 一律视为未通过。
2. AC 只有在它的**全部**证据行都是 `PASS` 或 `NOT_APPLICABLE`、且至少有一行 `PASS` 时才能标记为通过；出现 `FAIL` / `NOT_RUN` / `BLOCKED` 即视为未通过（部分通过不算通过）。
3. `actual` 与 `commit_sha` 在 `NOT_APPLICABLE` 之外为空属于证据缺失，不得算作通过。
4. `status` 写 `PASS` 但 `actual` / `notes` 实际表达“未执行 / 被阻塞 / 未验证”的，视为把未执行标成通过，直接退回。
5. 证据行 `commit_sha` 与矩阵声明的 head SHA 不一致即为证据过期；head 变化后必须在新 head 上重新取证，旧证据只能作为历史记录。
6. CI 绿灯、Agent 自述、聊天记录、历史 head 上的运行结果都不是当前 head 的充分证据。

**任务包结构化扩展字段** — 唯一权威定义（`local` 任务包与 `github` Issue 用同一组字段名）：

| 字段 | 必填 | 含义 | 填写规则 |
|------|------|------|----------|
| `invariants` | 是 | 必须始终成立、且可能被本次改动破坏的不变量 | 跨模块 / 跨步骤约束，或系统必须保持的性质 |
| `negative_cases` | 是 | 必须被拒绝、保持拒绝或保持不变的输入与操作路径 | 非法输入、越权路径、重复操作、冲突状态 |
| `migration_cases` | 是 | 旧数据 / 旧配置 / 旧版本输入的迁移与降级路径 | 含不迁移时的兼容行为与回滚动作 |
| `integration_paths` | 是 | 与其它模块、进程或外部系统的接触面 | 被改动的调用方、被依赖方与协议边界 |
| `unverified_assumptions` | 是 | 尚未验证、一旦不成立会推翻结论的假设 | 写明后续如何验证或由谁确认 |

这五个字段不得留空。小任务允许写 `N/A: <理由>`（必须带具体理由）；只写 `N/A` 或不写视为字段缺失，不得进入 `READY`。

结构检查：`python scripts/validate_kit.py` 默认校验模板内嵌样例与两底座字段一致性；`python scripts/validate_kit.py --task-packet <path>` 可单独校验一份填好的任务包（缺字段、空 AC、AC 无证据、`NOT_RUN` 被标成通过、SHA 不一致都会报错）。结构检查只证明“矩阵格式合法且没有把未执行标成通过”，不能代替 Master 的 G1 判定。

**旧任务兼容策略**：4.1 是**增量**要求，不改变既有状态机、门禁、权限与 `APPROVED` / `MERGED` / `VERIFIED` 的语义，也不引入新的状态。启用证据矩阵之前已派发或已进入审查的任务，其自然语言验收清单继续有效：Master 仍按 G1 逐条判定，只需在 PR 评论 / 任务记录中按 AC 编号补齐结论与证据引用，不必回填完整九字段矩阵。任务一旦在其任务包或 Issue 中声明使用证据矩阵，该任务整体按本节判定，不得部分回填后又按自然语言清单宣称通过。结构检查不追溯既有任务，也不把旧任务的缺失字段判为失败。

## 5. 运行时能力契约 C1–C4

在声称“可以派发子代理”之前，必须逐条探测并留下证据。**不得声称具备未探测的能力**；提示词里写了“支持”不等于运行时真的支持。

| 能力 | 契约要求 | 探测方式 | 通过判据 |
|------|----------|----------|----------|
| **C1 启动（spawn）** | 能启动一个执行实例，并返回可寻址句柄（ID / URL / 会话标识） | 启动一个只读探测任务，记录返回的句柄 | 句柄可再次定位到该实例；无句柄视为不通过 |
| **C2 隔离上下文** | 执行实例拥有独立上下文，不与其他任务共享可写会话状态 | 同时启动两个只读探测任务，检查彼此不可见对方的中间状态 | 上下文相互隔离；共享同一会话视为不通过 |
| **C3 等待取回** | 能等待实例结束，并取回状态、产物与证据（文件、命令输出、退出码、head SHA） | 让探测任务产生一个已知输出，再等待并取回 | 状态、产物、证据三者齐全且可核对 |
| **C4 区分终局** | 能区分成功、失败、取消，未知或空结果不得当作成功 | 分别制造成功、失败、取消三种探测终局 | 三种终局可区分；无法区分即不通过 |

探测流程：

1. 在任务记录（`local`：任务库事件；`github`：Issue 评论）写明运行时名称 / 版本、探测时间、探测任务 ID。
2. 逐条执行 C1–C4，记录命令、返回句柄、取回内容与终局判定。
3. 任一条不满足，则“由 Master 真实 spawn 并推进到 `DISPATCHED`”的路径**不可达**；必须降级为人工交接（`local` 的多会话交接或 `github` 的人工执行会话），并在任务记录中写明缺失能力、探测证据和降级方式。
4. 只有四条全部通过，才可使用子代理驱动路径；后续运行时升级或更换后必须重新探测。
5. 超时、取消、结果为空、句柄失效或状态不可判定，一律不得推进任务状态。

## 6. 底座切换

`local` → `github` 是唯一支持的迁移方向，必须一次性完成并记录切换点。**不允许双写**：同一任务不能同时在任务库和 Issue 中维护状态。

迁移清单：

1. **冻结写入**：停止 `local` 派发与状态变更，记录切换点的主分支 commit SHA 和任务库备份位置。迁移期间只允许只读查询。
2. **任务导出为 Issue**：每个未完成任务导出一个 Issue，字段按 `editions/github/ISSUE-TEMPLATE.md` 的五节填写（目标 / 验收标准 / 可改路径 / 禁改路径 / 依赖）；已完成任务只归档摘要，不重建活动 Issue。
3. **锁机制替换**：路径锁不再由 SQLite 承担。开工前在 Issue 写 `ORCH-TASK-REGISTRY` 登记块，并检查所有开放 PR 的变更文件是否与 `locked_paths` 相交；两者都通过才算取得锁。
4. **状态映射**：`PLANNED` / `READY` → Issue 创建并标注状态；`DISPATCHED` / `IN_PROGRESS` → 登记块 + 分支；`REVIEW_READY` → 先开 Draft PR（`PR_OPEN`）再转 Ready；`APPROVED` 的 head SHA 必须原样带入 PR；`MERGED` 以平台合并记录为准。
5. **证据迁移**：本地验证日志转为 PR 评论或 Issue 附件，并注明“迁移前本地证据”；迁移前的证据不能冒充迁移后 head 的 CI 结果，合并后必须在主分支重跑。
6. **合并后重验**：`local` 的 `VERIFIED` 不能直接继承。合并到主分支后按 G1–G6 重跑必需检查，通过后才在新底座标记 `VERIFIED`。
7. **收尾**：把任务库标记为只读归档，在 Issue 与 README 记录切换日期、切换点 SHA 和执行人；之后所有状态只写入 Issue / PR。

约束：

- 迁移是单向的。本套件不提供 `github` → `local` 的自动回退；确需回退时由项目所有者单独立项，重新导出为新的任务记录并重新验证。
- 迁移过程中不得让同一任务的旧状态与新状态同时被不同 Agent 当作事实来源；发现双写立即停止并升级为 `NEEDS_HUMAN_DECISION`。
- 底座切换属于重大架构取舍；执行前必须获得项目所有者批准并登记。

## 7. 项目接入与新项目

新项目的技术栈、目录与验证命令可能不存在。首次任务应是“项目初始化 / 技术方案 / 最小骨架”，而不是假设已有测试脚本。先记录产品目标、限制、假设与待人拍板问题，再通过当前底座的任务载体派发初始化任务。将未知验证项明确记为“待建立”，创建相应任务；不能声称尚不存在的命令已经通过。

## 8. 阶段收口

阶段只在必需任务达到 `VERIFIED`、相关风险已登记、阻塞与人工决策有明确去向、下一阶段任务已记录时算完成。汇报至少包含：范围与状态、已验证任务、仍阻塞事项、实际验证证据、未解决风险、下一步及需用户决定的事项。
