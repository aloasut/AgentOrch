# AGENT-ORCHESTRATION-ACCEPTANCE.md — 通用验收程序

每次首次接入、变更调度器 / 提示词，或更换 Agent 运行时后执行。证据必须来自真实命令和当前提交；不能将空模板、历史记录或 CI 绿灯当成已验收。本程序对两个底座通用，底座特有的检查项在标题中标注。修改核心契约、证据字段、模板、校验器、状态机 / 锁语义或发行流程时，除本程序对应段落外，还必须执行 **I 段（合成回归场景）**。

## A. 配置与底座识别

- [ ] `ORCHESTRATION-PROJECT.md` 中不再有未处理的 `FILL_IN`。
- [ ] `edition` 取值为 `local` 或 `github`；缺失或非法时引导流程会停止并报错，而不是猜测。
- [ ] 底座只由 `ORCHESTRATION-PROJECT.md` 的 `edition` 决定；`.orchestration/config.json` 里即使残留 `edition` 键也不影响路由（`config show` 标注为 ignored）。
- [ ] `edition` 缺失、为空、非法字符串、类型错误或文件不可读时，调度命令（`task add` / `ready` / `dispatch` / `status` / `workspace` / `amend` / `unlock`）以非零退出并报出实际值与修复位置；`init`、`backup`、`config show`、`task list`、`task show` 仍可用。
- [ ] 声明 `github` 时本地 CLI 拒绝调度并把下一步指向 Issue / PR，不冒充已支持 `github` 调度；`retry_cap` 的非法回退默认 `3` 语义未被牵连改变。
- [ ] 当前会话只使用一个底座；没有同时读写任务库与 Issue 的双写路径。
- [ ] 新 Master 上下文仅根据当前底座载体、Git 状态和证据记录恢复任务、活动锁、修复轮次与阻塞原因。
- [ ] 载体不可读 / 不可达时停止调度，而非从聊天记忆猜测。

## B. 活动任务锁与并行

- [ ] 两个路径完全不相交且无依赖的任务可分别取得锁。
- [ ] 同文件冲突及父目录 / 子文件冲突都被拒绝。
- [ ] 多路径任务若其中一条冲突，会整体拒绝；没有半套锁。
- [ ] 活动任务未生成分支 / Worktree 之前，锁也已登记。
- [ ] `VERIFIED` / `CANCELED` 后锁释放；`FAILED` / 状态未知时锁不自动释放。
- [ ] 强制解锁必须填写原因，并在事件记录中可追溯。
- [ ] `github`：开工前已检查所有开放 PR 的变更文件；登记块字段完整且时间戳单调递增。

### B2. 具名资源锁（语义只在 `docs/design/RESOURCE-LOCKS.md`，本节只列检查点）

- [ ] 任务声明了资源时，派发已同时通过路径锁与资源锁判定；未声明资源的任务行为与未启用资源锁时一致。
- [ ] 资源 ID 按契约 §2.1 规范化：拒绝大写 / 空格 / 通配 / `..`；冲突比较为精确匹配，不做前缀推导。
- [ ] 冲突矩阵与契约 §3.1 一致：`shared`/`shared` 允许，`shared`/`exclusive` 与 `exclusive`/`exclusive` 拒绝；`EXPIRED` / `QUARANTINED` 仍参与冲突判定。
- [ ] 多资源获取是原子集合：任一冲突则整批失败，失败后该任务非 `RELEASED` 锁行数为 `0`；申请顺序为确定性顺序。
- [ ] 只有 `VERIFIED` / `CANCELED` 自动释放；`FAILED` / `BLOCKED` / 状态未知保持占用，且不把过期当释放。
- [ ] 强制解锁与回收均有理由、授权与审计事件；无事件的锁记录被判为证据缺失并隔离，而非当作有效或空闲。
- [ ] `local` 只按契约 §7.1 的范围内声明原子互斥；`github` 的登记块与交付报告中没有“原子锁 / 并发已保证”一类表述。
- [ ] 契约 §9.1 的故障场景（F1–F9）在隔离环境演练过，每个场景有预期行为与证据形式；`FAILED` / 状态未知的自动释放未被演练“修复”为通过。
- [ ] 锁数据结构新增字段已随实现任务落地：`templates/TASK-PACKET.md` 的 `declared_resources` 与 `editions/github/ISSUE-TEMPLATE.md` 的 `locked_resources` 均为**可选**，留空不判失败，填写时只校验 `<id>:<mode>[:<ttl>]` 格式与逗号分隔。

## C. 合并门 G1–G6

- [ ] G1 每条验收标准都有独立依据；没有“部分通过即通过”。
- [ ] G1 的依据以 `AGENT-ORCHESTRATION.md` 4.1 节的证据矩阵记账：每条 AC 至少一条 evidence item，九个字段齐全，`actual` / `commit_sha` 在 `NOT_APPLICABLE` 之外不为空。
- [ ] G1 没有把 `NOT_RUN` / `BLOCKED` / `NOT_APPLICABLE` 折算为通过；带这类行的 AC 未被标记为通过。
- [ ] G1 证据行的 `commit_sha` 与矩阵声明的 head SHA 一致；head 变化后已在新 head 上重新取证。
- [ ] `python scripts/validate_kit.py` 通过；`--task-packet` 对合法样例判定通过、对缺字段 / 空 AC / 无证据映射 / `NOT_RUN` 冒充通过 / SHA 不一致判定失败。
- [ ] 旧任务按 4.1 节的兼容策略处理：未回填完整矩阵的既有任务仍按自然语言清单逐条判定，且没有被宣称“已通过矩阵验收”。
- [ ] G2 变更路径全部属于允许路径；没有未授权文件或夹带重构。
- [ ] G3 分支基于最新主分支，合并预演无冲突。
- [ ] G4 必需检查在当前 head SHA 全绿；`local` 为配置中的测试与静态检查，`github` 为 CI 工作流（`.github/workflows/ci.yml`：`pull_request`→`main`、`push`→`main`、`workflow_dispatch`；Python 3.12 / 3.13 矩阵；`permissions: contents: read`）。`github` 底座下 CI 含打包自检：两个 Python 版本都执行 `python scripts/build_release.py`，失败即 job 失败（无 `continue-on-error` / `|| true`），因此打包回归在 PR 上即可暴露；`py_compile` 同时覆盖 `scripts/check_drift.py`。
- [ ] `github`：G4 以**当前 head SHA** 的 CI 运行为主要证据，证据矩阵记录运行 URL 与 head SHA；可在 PR 的 Checks 区域或 `gh pr checks <PR 编号>` 复核。本地四条命令（`validate_kit`、`unittest`、`py_compile`、`build_release`）是补充证据，不能替代 CI；CI 绿灯同样不能折算为 G1 的逐条通过。

- [ ] G5 命令、输出、退出码与 head SHA 一致；失败测试未被删除、跳过或弱化。
- [ ] G6 新依赖、迁移、权限 / 安全变化与未实现行为已登记；需要决策时已进入 `NEEDS_HUMAN_DECISION`。
- [ ] 执行者无法直接把任务标记为 `APPROVED` / `MERGED` / `VERIFIED` 而绕过 Master 审查（至少在运行纪律及工具使用上验证）。
- [ ] head 变化会使先前 `APPROVED` 失效；`github` 底座还必须在新 head 上重跑 CI，旧 head 的绿灯不作为证据。
- [ ] 合并只由 Master 操作；合并后验证未通过时不能标记 `VERIFIED`。

## D. 运行时能力探测 C1–C4

- [ ] C1 启动返回可寻址句柄，且可再次定位。
- [ ] C2 两个探测实例的上下文相互隔离。
- [ ] C3 等待取回同时得到状态、产物与证据。
- [ ] C4 成功、失败、取消三种终局可区分。
- [ ] 任一能力不满足时，`DISPATCHED` 由 Master 真实推进的路径被判定为不可达，已记录探测证据并降级为人工交接。
- [ ] 没有把未探测的能力写进交付报告或提示词。

## E. 可控失败演练

在隔离的测试仓库或演练任务中执行，不得把故意缺陷合入真实主分支。

- [ ] 制造一项可控的验收缺口，Master 能指出具体门（G1–G6）、证据缺失和修复要求。
- [ ] 修复后在新的 head 上重新运行验证。
- [ ] 默认最多 3 轮审查—修复；第 3 轮仍失败则 `BLOCKED`，不派发第 4 轮。
- [ ] spawn 失败、超时、取消、结果为空或状态不可判定时，均不当作成功。
- [ ] `github`：CI 失败或 PR 变为不可合并时，不进入 `MASTER_REVIEW`。
- [ ] 演练记录含日期、运行时 / 版本、底座、任务 ID、每轮 head SHA、命令 / 退出码、结论和清理结果。

## F. 阶段收口审计（`templates/MILESTONE-AUDIT.md`）

局部任务审查通过不等于阶段可以收口。阶段收口时必须用 `templates/MILESTONE-AUDIT.md` 逐类给结论，而不是凭记忆宣布完成。

- [ ] 阶段收口使用 `templates/MILESTONE-AUDIT.md`，十类检查逐条有结论；不适用项写 `N/A: <理由>`，不以空白或删除标题代替。
- [ ] 每条结论都能回到任务、证据与 head SHA；缺其中任一项的结论不算已验证，不得记为通过。
- [ ] 结论只使用 `BLOCKING` / `NON_BLOCKING_HARDENING` / `OPTIONAL` / `NEEDS_HUMAN_DECISION` 四类（核实无问题记为 `PASS`）；`NOT_RUN` / `BLOCKED` / 未验证项没有被计为通过，也没有进入通过计数。
- [ ] 存在任一 `BLOCKING` 或 `NEEDS_HUMAN_DECISION` 时，阶段没有被标记为完成，也没有在计划、任务载体或交付报告里宣称已交付。
- [ ] 冻结契约与阶段审计对同一不变量给出一致结论；契约的任何改动都有 `templates/CONTRACT-DECISION-LOG.md` 记录（ID、日期、决定人、影响任务、变更前后、理由、状态、证据链接）。
- [ ] 已冻结、未决、后续可变更三类决策分别可查；未决项在收口结论里体现为 `NEEDS_HUMAN_DECISION`，没有被当成默认值。
- [ ] 审计没有复制 `AGENT-ORCHESTRATION.md` 的状态机或 G1–G6 定义，只引用；局部任务审查清单的结果没有被当作阶段收口证据。

## G. 证据模板

```text
日期与运行环境：
项目 / 分支：
底座（local / github）：
测试任务 ID：
任务载体备份 / Issue 链接：
调度能力实际探测（C1–C4）：
活动任务锁测试命令与结果：
具名资源锁检查与演练场景编号（F1–F9）及结论：
证据矩阵位置（任务记录 / PR 评论）：
矩阵声明的 head SHA 与各证据行 commit_sha 是否一致：
CI 运行 URL 与 head SHA（`github` 底座）：
阶段收口审计位置（`templates/MILESTONE-AUDIT.md`）与审计 head SHA：
阶段审计结论计数（BLOCKING / NON_BLOCKING_HARDENING / OPTIONAL / NEEDS_HUMAN_DECISION）：
是否存在 BLOCKING 或 NEEDS_HUMAN_DECISION（存在时阶段不得标为完成）：
冻结契约 / 决策日志位置与未决项（`templates/DESIGN.md`、`templates/CONTRACT-DECISION-LOG.md`）：
未执行项（NOT_RUN / BLOCKED / NOT_APPLICABLE）及其理由：
失败演练轮次与 head SHA：
第 3 轮后是否 BLOCKED：
合并后验证命令 / 退出码：
能力登记位置（`templates/RUNTIME-CAPABILITY.md`）与记录状态（COMPLETE / PARTIAL / STALE）：
未探测或已失效的能力（`UNKNOWN`）及对应降级方式：
指标报告命令、窗口与来源（`scripts/report_metrics.py`，`local` 任务库或事件样本）：
各指标的样本量 / 缺失率 / coverage（未采集项标 `unknown`）：
已知限制与未测试项：
最终结论：通过 / 部分通过 / 未通过
```

## H. 能力登记与交付度量

D 段只回答“C1–C4 是否通过”。本节回答“这些结论记在哪里、什么时候失效”以及“交付质量数字是怎么算出来的”。两者都不改变状态机、G1–G6 或 `VERIFIED` 的语义。

- [ ] 每个真实使用过的运行时 / 版本 / 底座 / 执行模式组合都有一份 [templates/RUNTIME-CAPABILITY.md](templates/RUNTIME-CAPABILITY.md) 记录；同一运行时换了版本即视为新记录。
- [ ] 记录含运行时名称与精确版本、底座、执行模式、探测时间（UTC）、探测任务 ID、证据引用与限制；缺任一字段不得记为 `COMPLETE`。
- [ ] 未探测的能力写 `UNKNOWN`，没有把“提示词里写了支持”当作能力；C1–C4 任一条不是 `PASS` 时，子代理路径被判定为不可达并已降级为人工交接。
- [ ] 运行时升级 / 降级、底座切换、执行模式或证据载体变化后，受影响能力已降级为 `UNKNOWN` 并重新探测；没有出现“其余照旧”式的整体沿用。
- [ ] 能力记录的 `Limits` 写明了未覆盖范围；记录中没有把 `PASS` 表述成“已获得权限”，也没有替代任务允许路径、项目访问控制与 G4 的 CI 检查。
- [ ] 记录中不含凭据、会话信息或提示词原文。
- [ ] [templates/METRICS.md](templates/METRICS.md) 的七项指标都有起止事件、时区、排除项与缺失处理；口径改动有日期与理由，脚本与文档没有两套定义。
- [ ] `python scripts/report_metrics.py --gold-sample --since 2026-01-01 --until 2026-02-01` 复现金样本；数值与模板中记载的期望值一致，说明样本可复现。
- [ ] 空输入得到 `no data` 与 coverage 0，而不是 0 值；缺事件的任务记为 `missing`，未采集的记录类型记为 `unknown`。
- [ ] 报告只读取事件与证据引用，没有读取凭据、提示词或消息正文；`--json` 的字段名与顺序稳定。
- [ ] 任何被引用的指标都附带样本量、窗口与缺失率，且没有被用作没有上下文的 Agent / 人员 / 运行时排名。
- [ ] `validate_kit.py` 校验两份模板的必备章节；章节被删除即失败。

## I. 合成回归场景（套件重大变更必跑）

修改 `AGENTS.md` / `AGENT-ORCHESTRATION.md` 的核心条款、4.1 证据字段、模板结构、`scripts/validate_kit.py`、状态机或锁语义、发行流程时，必须执行本节。场景目录、注入的缺陷与预期拦截门只在 `docs/testing/DELIVERY-REGRESSION-SCENARIOS.md`，本节只列验收动作。

- [ ] `python scripts/run_delivery_scenarios.py --json` 退出码为 `0`；退出码 `1`（有场景失败）与 `2`（运行器未能开跑）不得当作通过。
- [ ] `totals.negative_passed` 等于 `totals.negative`：负向组“通过”表示拦截真的发生了，不是任务真的失败了。至少一个正向控制组为 `PASS`，否则不能排除“所有任务都失败”。
- [ ] `totals.errors` 为 `0`；若不为 `0`，报告必须保留异常类型与堆栈，并且剩余场景仍已执行完（单场景失败不吞掉后续）。
- [ ] 本次变更涉及的场景已同步更新：场景表的 ID 与运行器注册一致（`tests/test_run_delivery_scenarios.py` 会检查 `| <ID> |` 行）。
- [ ] 报告的 `generated_at` / `python` / `platform` 与本次证据记录一致；报告用 `--output` 写到仓库外，未提交进仓库。
- [ ] `local` 可离线完成的范围：A–D 四组的核心门语义（证据矩阵与空 AC、`NOT_RUN` 冒充 `PASS`、旧 head、edition fail-closed、路径锁与具名资源锁冲突、修复轮数、阶段审计 `BLOCKING` / `NEEDS_HUMAN_DECISION`）。
- [ ] `github` 可离线完成的范围：同一套字段、模板与校验函数；Issue / PR / 登记块 / CI 端到端**无法离线验证**，未实际运行即标 `BLOCKED`，不得用 `local` 结果替代。
- [ ] 场景只证明套件自身的门禁；不得据此宣称对任何外部产品项目做过真实数据或自动化验证。

