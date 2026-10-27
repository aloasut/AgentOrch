# AgentOrch 阶段计划（2026-10）

> 本文件是**阶段目标与执行路径的唯一权威**：阶段划分、每阶段的交付与出口、任务顺序与依赖、当前状态都在这里。
> 设计目标（为什么做、做到什么程度、原则与边界）只在 [PLAN.md](PLAN.md)（1.4 起位于 `docs/`）；字段、状态取值与合并门语义只在 [kit/orchestration.md](../kit/orchestration.md) 4.1 与第 5 节，本文件只引用不重述。
> 本文件只经任务分支 + PR 修改。与 `PLAN.md` 的设计目标冲突时，以设计目标为准并停下对齐，不得各写一套。

- 版本：v3.4（S1 已完成 / `VERIFIED`；S2 进行中；上一版 v3.3 记录 S2 `READY`，更早的 v3.2 记录 S1 进行中（PR #127），v3.1 / v3.0 记录 Phase D 阶段计划登记、#99–#104 收口与本轮 1.6.3 发布事实，真实 `1.6.2 → 1.6.3` 升级 `APPLIED`）
- 日期：2026-10-27
- 状态：Phase A / B / C 已交付；Epic #46 的 S0–S6 与两项支撑修复均已合并并 `VERIFIED`，Epic 已按阶段审计关闭（[审计评论](https://github.com/ctrlshiftaltdel/AgentOrch/issues/46#issuecomment-6415751115)）；**`v1.6.3` 是最新发布**（[Release v1.6.3](https://github.com/ctrlshiftaltdel/AgentOrch/releases/tag/v1.6.3)，tag `v1.6.3` → `2adf431`，资产 `AgentOrch-1.6.3.zip`，461,829 bytes，SHA256 `dcce5b24…`），发布属性为 Format 1.6、754 tests、92 个 `REQUIRED` 文件（发行包 93 = 92 + `MANIFEST.json`）、58/58 场景、四平台 CI 通过；上一个发布 `v1.6.2`（[Release v1.6.2](https://github.com/ctrlshiftaltdel/AgentOrch/releases/tag/v1.6.2)，资产 `AgentOrch-1.6.2.zip`，SHA256 `096e1fba…`）为 Format 1.6、715 tests、91 文件包（90 `REQUIRED` + `MANIFEST.json`）、58/58 场景、四平台 CI 通过；#85、#86、#93、#95、#99–#104 与 #113 均已 `VERIFIED`；真实 `1.6.2 → 1.6.3` 隔离升级结果为 `APPLIED`（§12）；当前唯一未完成硬化项为 #73（`NON_BLOCKING_HARDENING`），#71、#72 已由后续任务收口并 `VERIFIED`；**Phase D（Agent 角色发现、Subagent 能力考核与动态模型选型）已按 §13 登记**：设计冻结 #117 已通过 PR #118 合并 `ceb2c0a` 并 `VERIFIED`，阶段计划登记 #125 已 `VERIFIED`；S1 #120 已 `VERIFIED`（PR #127 合并 `818adaa`；主分支 813 tests / 98 `REQUIRED` / 58/58 / `build_release` SHA `e32dda30…`）；S2 #121 进行中（当前 PR 见 Issue #121 登记；依赖 #120、#125 已满足）；#122–#124 仍 `BLOCKED`，等待各自前置任务 `VERIFIED`；Phase D 是新增阶段，不改变 #73 仍是唯一未完成硬化项的结论
- 适用范围：AgentOrch 核心规则、local/github edition、任务模板、验证脚本与发行机制
- 设计目标来源：[PLAN.md](PLAN.md)

## 1. 当前状态（2026-10-27）

状态变化的唯一落点就是这张表；`PLAN.md` 的设计目标不随任务状态变化。

| 任务 | 交付重点 | 依赖 | 状态 | 依据 |
|---|---|---|---|---|
| [#2](https://github.com/ctrlshiftaltdel/AgentOrch/issues/2) 结构化验收证据矩阵 | 任务字段、证据映射、负向 / 迁移场景、结构测试 | Epic [#1](https://github.com/ctrlshiftaltdel/AgentOrch/issues/1) | 已完成 | Issue 已关闭；字段契约落在 `kit/orchestration.md` 4.1 |
| [#4](https://github.com/ctrlshiftaltdel/AgentOrch/issues/4) edition 权威来源与 fail-closed | 区分项目底座与 CLI 配置、合法 / 非法 / 损坏配置测试 | Epic #1 | 已完成 | Issue 已关闭；`docs/PROJECT.md` 的 `edition` 为唯一权威 |
| [#14](https://github.com/ctrlshiftaltdel/AgentOrch/issues/14) GitHub Actions 接入 | PR 上跑规则包校验、单元测试与语法检查 | Epic #1 | 已完成 | Issue 已关闭；`.github/workflows/ci.yml` |
| [#15](https://github.com/ctrlshiftaltdel/AgentOrch/issues/15) 根 `PLAN.md` 与 `init` 初始化 | `init` 生成设计目标文件；阶段目标与执行路径由 #19 拆分到本文件 | #2 | 已完成 | PR #18 已合并；`init` 冒烟与单元测试 |
| [#19](https://github.com/ctrlshiftaltdel/AgentOrch/issues/19) 拆分计划层 | `PLAN.md` 只写设计目标，阶段目标与执行路径移入本文件 | #15 | 已完成 | 本文件 v2.0 与 `templates/implementation-plan.md` |
| [#5](https://github.com/ctrlshiftaltdel/AgentOrch/issues/5) 共享资源锁契约 | 冻结 shared/exclusive、所有权、租约、恢复语义 | #2（模板字段已就绪） | 已完成 | PR #21 已合并（`d89f1f7`）；`docs/design/resource-locks.md` v1 |
| [#3](https://github.com/ctrlshiftaltdel/AgentOrch/issues/3) 设计契约与阶段收口审计模板 | 冻结项 / 待决项、跨模块不变量、审计分类 | #2（可先起草）、#5 口径 | 已完成 | PR #24 已合并（`bea370c`）；三份模板 + 章节校验 |
| [#6](https://github.com/ctrlshiftaltdel/AgentOrch/issues/6) 具名资源锁实现 | 原子获取 / 释放、并发测试、冲突原因、人工恢复 | #5 | 已完成 | PR #23 已合并（`53a0ca6`）；`task resources/renew` 与并发演练 |
| [#7](https://github.com/ctrlshiftaltdel/AgentOrch/issues/7) 发行清单与漂移诊断 | 版本、核心 SHA-256、只读差异报告、打包完整性 | Epic #1 | 已完成 | PR #22 已合并（`d085092`）；`MANIFEST.json` + `check_drift.py` |
| [#8](https://github.com/ctrlshiftaltdel/AgentOrch/issues/8) 运行时能力登记与交付指标 | 能力证据、新鲜度、指标口径、缺失数据 | #2 | 已完成 | PR #26 已合并（`25d1573`）；`report_metrics.py` 七项指标 |
| [#13](https://github.com/ctrlshiftaltdel/AgentOrch/issues/13) edition 旧格式升级说明 | 发布前的迁移说明 | #4 | 已完成 | PR #27 已合并（`870109a`）；README §10 + `docs/upgrade.md` |
| [#17](https://github.com/ctrlshiftaltdel/AgentOrch/issues/17) 发布自检纳入 CI | 把 `build_release` 自检放进流水线 | #14（已满足） | 已完成 | PR #25 已合并（`53a86fc`）；CI 两档跑打包自检，`VERSION.md` 1.3 |
| [#9](https://github.com/ctrlshiftaltdel/AgentOrch/issues/9) 合成回归与通用验收集成 | 故障注入、集成矩阵、失败演练、发布出口 | #2 / #3 / #4 / #5；最终验收等 #6–#8 | 已完成（随本 PR 合并生效） | 本 PR：`scripts/run_delivery_scenarios.py` + 场景文档 + 验收程序 I 段 |

已完成只代表交付完成，不代表该阶段已验证；每条交付仍以对应 PR 的逐条验收结果、以及合并后主分支上重跑的结果为准。Phase A / B / C 的原有任务已交付。Epic [#46](https://github.com/ctrlshiftaltdel/AgentOrch/issues/46) 的 S0–S6（[#47](https://github.com/ctrlshiftaltdel/AgentOrch/issues/47)–[#52](https://github.com/ctrlshiftaltdel/AgentOrch/issues/52)）、首批经验落地（[#55](https://github.com/ctrlshiftaltdel/AgentOrch/issues/55)、[#56](https://github.com/ctrlshiftaltdel/AgentOrch/issues/56)）与两项支撑修复（[#62](https://github.com/ctrlshiftaltdel/AgentOrch/issues/62)、[#66](https://github.com/ctrlshiftaltdel/AgentOrch/issues/66)）均已合并并按任务载体标为 `VERIFIED`；最终验收任务 [#53](https://github.com/ctrlshiftaltdel/AgentOrch/issues/53) 经 PR [#70](https://github.com/ctrlshiftaltdel/AgentOrch/pull/70) 合并 `6ac9573` 后标为 `VERIFIED` 并关闭。Epic #46 已于 2026-10-26 按 `templates/milestone-audit.md` 完成阶段审计并关闭（[审计评论](https://github.com/ctrlshiftaltdel/AgentOrch/issues/46#issuecomment-6415751115)），审计无 `BLOCKING` 项。审计登记的三项 `NON_BLOCKING_HARDENING` 中，[#71](https://github.com/ctrlshiftaltdel/AgentOrch/issues/71)（真实 Release 升级，PR #82 合并 `4a7069e`）与 [#72](https://github.com/ctrlshiftaltdel/AgentOrch/issues/72)（跨平台实机，由 #77 的跨平台 CI 收口，PR #79 合并 `e26902f`）已完成并标 `status:verified`；[#85](https://github.com/ctrlshiftaltdel/AgentOrch/issues/85)（下游包修复，PR #87 合并 `72a39e4`）与 [#86](https://github.com/ctrlshiftaltdel/AgentOrch/issues/86)（发布 1.6.1，PR #88 合并 `baa5c91`）也已 `VERIFIED`，`v1.6.1` 已发布（资产 `AgentOrch-1.6.1.zip`，SHA256 `7b70d722…`）。1.6.1 之后的补丁链同样收口：[#93](https://github.com/ctrlshiftaltdel/AgentOrch/issues/93)（`task add` 重复多值选项修复，PR [#94](https://github.com/ctrlshiftaltdel/AgentOrch/pull/94) 合并 `35fb924`）与 [#95](https://github.com/ctrlshiftaltdel/AgentOrch/issues/95)（发布 1.6.2，PR [#96](https://github.com/ctrlshiftaltdel/AgentOrch/pull/96) 合并 `bab65b6`）已 `VERIFIED`，`v1.6.2` 已发布（[Release v1.6.2](https://github.com/ctrlshiftaltdel/AgentOrch/releases/tag/v1.6.2)，资产 `AgentOrch-1.6.2.zip`，SHA256 `096e1fba…`；Format 1.6、715 tests、58/58 场景、四平台 CI 通过）。1.6.2 发布后的 [#99](https://github.com/ctrlshiftaltdel/AgentOrch/issues/99)–[#104](https://github.com/ctrlshiftaltdel/AgentOrch/issues/104) 六项（对应 PR #105–#110）也已合并并 `VERIFIED`，同样不属于审计硬化项；#104 合并后的 `main`（`51e418f`）的 754 tests、92 个 `REQUIRED` 文件（发行包 93）、58/58 场景与四平台 CI 反映的是这六项合并后的状态；`v1.6.3` 已在其上于 2026-10-27 发布（tag `v1.6.3` → `2adf431`，详见 §12）。只剩 [#73](https://github.com/ctrlshiftaltdel/AgentOrch/issues/73)（场景运行器拆分）仍 `OPEN`，在 §11 单独登记为未完成硬化项；不得据此宣称真实 1.6.0 → 1.6.1、1.6.0 / 1.6.1 → 1.6.2 升级、真实 1.3 / 1.4 资产升级、以 **1.6.0 / 1.6.1** 为已安装基线、真实断网、HD-11 或非 GitHub-hosted 平台已验证。

## 2. 为什么要分阶段

本轮升级不重新发明多 Agent 工作流，而是补足现有流程中依靠执行者 / 审查者自觉完成的部分：把关键规则转成结构化字段、可重复的检查、故障演练和可追溯报告。三个近期项目给出的输入：

- **AgentMgr：治理状态与权限边界。** 授权撤销、任务重试 / 租约、审计上下文与审批可见性，需要负向、竞态与跨接口验证，而不只验证正常请求。
- **TalkDND：规则版本、旧数据与发行可靠性。** 规则目录隔离与角色数据迁移说明，功能新增需考虑旧数据、幂等重跑、版本隔离与回滚。
- **NotDND：系统级不变量。** 设计冻结与 E2E 工作、战斗时钟、行动者权限、事件链等在办问题说明，模块测试通过不代表完整交互闭环正确。

这些项目只作为经验来源；回归场景使用合成 fixture，不复制产品仓库的内部数据、私有信息、凭据或受版权保护内容。

当前已有资产（不需要重建）：两种底座与共用核心契约；任务状态机、依赖、活动路径锁与异常锁保留策略；合并门、head SHA 绑定与合并后验证；运行时能力探测与降级为多会话交接的原则；任务包 / 计划 / 审查 / 验收模板；纯标准库实现与套件结构校验。

## 3. 待解决的差距

1. 合并门要求逐条证据，但任务模板缺统一的、可机器检查的证据映射、负向场景与跨模块不变量结构。
2. 复杂项目需要设计契约与阶段审计，但阶段检查依赖 Master 阅读多处文档、凭上下文汇总。
3. 路径锁无法表达测试数据库、共享构建环境、共享生成产物等具名资源冲突。
4. 底座要求非法 `edition` 失败关闭，而 CLI 配置读取对若干非法 / 缺失值回退默认；项目底座与本地 CLI 配置的边界需要说清并测试（#4 已关闭，边界仍要在 #13 的升级说明里固化）。
5. 下游项目复制套件后缺少版本清单 / 漂移诊断；自动同步又可能覆盖项目特有政策。
6. 运行时能力探测是必要基础，但缺少面向交付物类型、权限、环境与证据新鲜度的登记；流程指标也缺统一口径。
7. 套件自身需要能反复演练跨模块失败场景，而不只在文档里要求 Agent“检查”。

## 4. 阶段目标、交付与出口

### Phase A — 契约和验收基础

- **阶段目标**：让“任务该怎么被验收”与“共享资源怎么被占用”都有唯一、可冻结的契约，后续实现不再各自发明字段。
- **交付**：
  - 任务包证据矩阵、负向场景、迁移场景与跨模块不变量字段（#2，已完成）。
  - edition 权威来源和 fail-closed 语义（#4，已完成）。
  - 根 `PLAN.md` 计划初始化与计划层拆分（#15、#19，已完成）。
  - Design Contract 与 Milestone Audit 模板（#3）。
  - 共享资源锁设计契约（#5）。
- **出口条件**：
  - 核心字段、证据与状态语义有唯一权威定义，模板只引用不重述。
  - 两个底座字段含义一致，差异只在载体与证据来源。
  - 资源锁契约覆盖并发、崩溃、租约过期、强制解锁与恢复行为。
  - 配置缺失 / 非法行为可用测试证明，且不破坏既有 `local` 状态库。
  - 新增文档内容通过规则包校验，命令证据来自真实执行。

### Phase B — 调度、漂移和能力可观测性

- **阶段目标**：把 Phase A 冻结的契约落成可运行能力，并让“漂移”和“能力”都有只读、可复核的观测手段。
- **交付**：
  - 按冻结契约实现具名资源锁及冲突诊断（#6），保持既有路径锁向后兼容。
  - 发行清单及只读的套件版本 / 核心契约漂移诊断（#7）。
  - 运行时能力登记、度量定义及最小只读报告（#8）。
- **出口条件**：
  - 锁竞争不会产生半套锁、重复所有权或静默释放。
  - 漂移诊断不修改目标仓库；下游特有文件被识别为扩展，而不是自动覆盖对象。
  - 能力清单区分支持 / 不支持 / 未知 / 过期，并链接真实测试证据。
  - 指标定义精确、可复现，显式报告缺失数据与样本量。

### Phase C — 合成回归与发布验收

- **阶段目标**：用可重复的合成场景证明整套流程会在该失败的地方失败，而不是只在文档里要求“要检查”。
- **交付**：
  - 四类合成场景：治理 / 授权、数据迁移 / 版本隔离、跨模块闭环、编排底座与证据失效（#9）。
  - 把新检查纳入通用验收程序与 README。
  - 在隔离环境中做可控失败演练，并保存最终证据。
- **出口条件**：
  - 正向控制组与负向失败组都覆盖；场景可重复运行，不依赖真实密钥、外部模型、外部业务服务或私有数据。
  - `local` / `github` 核心验收语义一致；无法离线验证的 GitHub 特有动作明确标为待验证 / 阻塞。
  - 旧 SHA、证据缺失、锁冲突、异常测试终止与待人工决定项不会被误报为 `VERIFIED`。
  - 完整测试在当前 head 实际通过，或未通过项有明确阻塞记录；不以历史 CI 或旧 commit 代替。

### 发布门前置（与 Phase B / C 并行）

- **阶段目标**：补齐下一次发布前必须闭环的两项，避免发布说明缺迁移路径、发布自检漏出流水线。
- **交付**：#13 edition 旧格式升级说明；#17 把 `scripts/build_release.py` 自检纳入 CI。
- **出口条件**：升级说明覆盖旧格式项目；发布自检在 CI 上随 PR 执行并在当前 head 通过。

## 5. 任务顺序与依赖

派发顺序（依赖未满足就停在 `PLANNED`，不提前开工）：

1. **#5**（Phase A，设计冻结）——下一步。
2. **#3**（Phase A，模板与契约口径对齐；#5 结论定稿后再定稿）。
3. **#6**（Phase B，依赖 #5 已验收）。
4. **#7** 与 **#8**（Phase B，可并行，路径不重叠）。
5. **#9**（Phase C，依赖 #2 / #3 / #4 / #5；最终验收等 #6–#8）。
6. **#13** 与 **#17**（发布门前置，可与 Phase B / C 并行）。

并行与路径规则：

- #2 与 #4 的锁定路径在 `scripts/validate_kit.py`、`tests/`、`kit/orchestration.md` 上相交，按路径锁规则**串行**完成，并非并行完成的先例。跨文件并行的前提是锁定路径不相交；不得用“计划上允许并行”代替实际的冲突检查。
- #3 的模板可先起草；与任务模板共用路径时必须协调所有权，不能并行编辑同一 Worktree 或同一文件。
- #5 是设计冻结任务；#6 不得在 #5 验收前开始实现锁语义。
- #7 与 #8 可并行，但须分配不重叠路径；变更发行清单 / 校验器的任务独占相关路径。
- #9 可提前起草场景，最终集成验收必须等依赖能力完成并在当前 head 上重跑。
- 全量测试资源用独占资源锁；并发数按机器余量与任务冲突判断，不以固定数字取代检查。
- 任何修改超出任务路径必须停下、更新授权并重新检查冲突。
- Phase D（#117 / #119 / #120–#124）的顺序、依赖与出口条件见 §13。

## 6. 跨项目合成回归矩阵（Phase C 的输入）

| 场景组 | 经验来源 | 合成失败注入 | 预期拦截 |
|---|---|---|---|
| G — 治理 / 授权 | AgentMgr 的 grant 撤销、重复写、审计与任务重试 | 过期 / 撤销授权、重复提交、审计关联缺失、并发状态变化 | 负向验收失败；授权 / 审计证据不完整不能通过 |
| M — 迁移 / 版本 | TalkDND 的旧角色数据与规则版本隔离 | 旧格式升级、迁移重跑、目标版本混用、写入一半后故障 | 幂等 / 回滚验收失败时阻断；迁移证据明确 |
| X — 跨模块闭环 | NotDND 的战斗状态、时钟、单位所有权与事件链 | 契约规则未接线、越权对象 ID、事件屏障遗漏、非断言异常 | 端到端 / 不变量检查失败；测试仍输出总结报告 |
| O — 编排器本身 | AgentOrch 的底座、锁与证据门 | 非法 edition、重叠资源锁、旧 SHA、缺证据、超过修复上限 | 不能进入 `APPROVED` / `MERGED` / `VERIFIED`；原因可定位 |

所有 fixture 只模拟数据结构与行为，不复制三个产品项目的专有业务数据或受版权文本。至少保留一个通过控制组，避免回归套件只会报告失败。

## 7. 阶段收口（Milestone Audit）

阶段结束不以“子任务全部关闭”为判定依据。Master 在阶段收口时汇总：

- 必需功能与不变量是否逐项验证；
- 安全 / 隐私、迁移兼容性与回滚；
- 端到端完整路径与错误恢复；
- 性能基线（只有实际测量才下结论）；
- 已知缺口分类及其后续任务；
- 当前主分支 SHA 上的完整检查结果。

缺口按三类处理：`BLOCKING`（阶段不得标为完成）、`NON_BLOCKING_HARDENING`（可继续，但须写明风险、跟踪任务与接受依据）、`NEEDS_HUMAN_DECISION`（保留阻塞，不代替所有者做决定）。

单个任务的验收字段、证据条目格式与合并门判定，直接在 `kit/orchestration.md` 4.1 与第 5 节执行；本文件不复制这些定义，也不替它们做解释。

## 8. 回退与风险处理

- **文档 / 模板变更**：通过单独分支与 PR 回退；不删改历史记录。
- **资源锁实现**：先兼容既有路径锁；新资源锁异常不得自动解锁全部活动任务，状态不明先阻断并人工复核。
- **配置行为**：旧合法 `local` 配置保持兼容；迁移需要单独测试与记录。不支持的 `github` CLI 行为明确失败，不冒充可执行。
- **版本漂移**：诊断只读，不自动覆盖；修复由各项目自己的任务 / PR 完成。
- **指标**：缺数据标 `UNKNOWN` / coverage，不用估算值填补。
- **测试**：不得通过删除断言、放宽验收、吞掉异常或把检查移出配置来“修绿”。
- **发布**：清单、包内容、脚本与模板校验通过后才能发布；发布说明标出新增功能、兼容性边界与未验证能力。

## 9. 阶段收口检查清单

- [ ] 两个底座使用相同的任务与审查语义。
- [ ] 任务证据矩阵、设计契约、阶段审计模板齐全。
- [ ] 配置缺失、非法、损坏与未支持的底座行为均有测试。
- [ ] 路径锁与具名资源锁职责明确，且有并发 / 故障演练。
- [ ] 漂移诊断只读，清单可重现、哈希可复核。
- [ ] 运行时能力与质量指标基于真实来源并标明缺失数据。
- [ ] 四类合成回归场景含正向组、负向组、证据与清理步骤。
- [ ] 当前 head 的规则包验证、单元测试、发行包检查全部实际执行。
- [ ] 主分支合并后重跑完整验证，并记录命令、退出码、SHA、审查结论与遗留风险。

项目级、可度量的全局验收标准在 [PLAN.md](PLAN.md) 第 6 节；本节只列阶段收口还需要确认的项。

## 10. 维护规则

- **只经 PR 修改**：本文件的任何变更都要走任务分支 + PR + 独立审查；不在会话里口头改计划而不落文件。
- **状态只写第 1 节**：任务状态、当前阶段与“下一步”只改第 1 节；设计目标改动才动 `PLAN.md`。
- **先计划后登记**：新任务先写进第 1 节与第 5 节顺序，再登记为 Issue / 任务；关闭或取消的任务保留行并注明结果，不删除历史。
- **不复制定义**：字段、状态与门禁语义始终引用 `kit/orchestration.md`；发现本文件与核心文档口径不一致，先停下对齐，不在两处各写一套。
- **冲突处理**：与本文件的设计目标来源 `PLAN.md` 冲突时，以设计目标为准并停下对齐。


## 11. 自我完善与安全更新（新增规划，2026-10-26）

详细设计唯一落点：[docs/self-improvement-and-update-plan.md](self-improvement-and-update-plan.md)。本节只维护阶段顺序、依赖和状态，不复制设计契约。

| Issue | 交付重点 | 依赖 | 状态 |
|---|---|---|---|
| [#47](https://github.com/ctrlshiftaltdel/AgentOrch/issues/47) | 冻结来源注册表、Lesson 生命周期、Architecture Contract、更新安全与威胁模型 | Epic #46 | 已完成（PR #57 合并 `73a9c03`；Issue 已关闭并标 `status:verified`） |
| [#48](https://github.com/ctrlshiftaltdel/AgentOrch/issues/48) | 项目可配置架构契约与依赖边界检查器 | #47 | 已完成（PR #59 合并 `a9312dc`；Issue 已关闭并标 `status:verified`） |
| [#49](https://github.com/ctrlshiftaltdel/AgentOrch/issues/49) | TalkDND / AgentMgr 可配置来源、经验采集、验证与去重 | #47；共享路径需等 #48 | 已完成（PR #61 合并 `eaeb4e9`；Issue 已关闭并标 `status:verified`） |
| [#55](https://github.com/ctrlshiftaltdel/AgentOrch/issues/55) | TalkDND 已知模块边界、共享状态、并发、回滚和失败语义经验的首批规则 / 回归场景 | #47；架构专项检查依赖 #48 | 已完成（PR #63 合并 `6666e15`；Issue 已关闭并标 `status:verified`） |
| [#56](https://github.com/ctrlshiftaltdel/AgentOrch/issues/56) | AgentMgr 已知契约优先、Runtime Adapter 隔离、共用应用层和证据边界经验的首批架构回归场景 | #47、#48 | 已完成（PR #64 合并 `698f779`；Issue 已关闭并标 `status:verified`） |
| [#50](https://github.com/ctrlshiftaltdel/AgentOrch/issues/50) | “进行自我完善”触发、计划、派发、执行与验证闭环 | #48、#49；首批经验场景参考 #55、#56 | 已完成（PR #68 合并 `2d55da9`；Issue 已关闭并标 `status:verified`） |
| [#51](https://github.com/ctrlshiftaltdel/AgentOrch/issues/51) | 官方 Release 校验、三方比较、冲突分类、备份与回滚 | #47；共享路径需等 #48 | 已完成（PR #60 合并 `a9ab779`；Issue 已关闭并标 `status:verified`） |
| [#62](https://github.com/ctrlshiftaltdel/AgentOrch/issues/62) | 对齐 Lesson T10 与 `GENERAL_LESSON` 的 `NEEDS_VERIFICATION` 状态 | #47 | 已完成（PR #65 合并 `c09352c`；Issue 已关闭并标 `status:verified`） |
| [#66](https://github.com/ctrlshiftaltdel/AgentOrch/issues/66) | 隔离 architecture 路径穿越测试的固定 `/tmp` 文件 | #48 | 已完成（PR #67 合并 `66a659e`；Issue 已关闭并标 `status:verified`） |
| [#52](https://github.com/ctrlshiftaltdel/AgentOrch/issues/52) | “更新 AgentOrch”入口、迁移指南与发行包接入 | #51 | 已完成（PR #69 合并 `6756249`；Issue 已关闭并标 `status:verified`） |
| [#53](https://github.com/ctrlshiftaltdel/AgentOrch/issues/53) | 自我完善 / 更新流程合成回归、端到端演练与趋势报告：A8–A15 / B5–B14 / C19–C20 / D8–D9 场景与指标契约测试接入；CI 与发行包自检纳入 | #48–#52、#55、#56 | 已完成 / `VERIFIED`（PR [#70](https://github.com/ctrlshiftaltdel/AgentOrch/pull/70) 合并 `6ac9573`；Issue 已关闭并标 `status:verified`；当前 head 的逐条证据见 [VERIFIED 评论](https://github.com/ctrlshiftaltdel/AgentOrch/issues/53#issuecomment-6415723538)） |
| [#74](https://github.com/ctrlshiftaltdel/AgentOrch/issues/74) | 用 TalkDND / AgentMgr 运行首轮真实经验扫描 | #47、#49 | 已完成 / `VERIFIED`（PR [#80](https://github.com/ctrlshiftaltdel/AgentOrch/pull/80) 合并 `43f9c3c`；539 条证据（TalkDND 316 / AgentMgr 223），两来源均 `PARTIAL`，无 `OK` 水位；与既有经验去重后无候选；Issue 已关闭并标 `status:verified`） |
| [#76](https://github.com/ctrlshiftaltdel/AgentOrch/issues/76) | 发布 AgentOrch 1.6（`AgentOrch-1.6.zip`，Format 1.6） | #52、#74 | 已完成 / `VERIFIED`（PR [#81](https://github.com/ctrlshiftaltdel/AgentOrch/pull/81) 合并 `eac7f8e`；[Release v1.6](https://github.com/ctrlshiftaltdel/AgentOrch/releases/tag/v1.6)，资产 SHA256 `bc0a64e3…`；Issue 已关闭并标 `status:verified`） |
| [#77](https://github.com/ctrlshiftaltdel/AgentOrch/issues/77) | CI 增加 macOS / Windows 实机 job | #14、#53 | 已完成 / `VERIFIED`（PR [#79](https://github.com/ctrlshiftaltdel/AgentOrch/pull/79) 合并 `e26902f`；四平台四 job 全绿：Linux 3.12 / 3.13、macOS 3.13、Windows 3.13；Issue 已关闭并标 `status:verified`） |
| [#71](https://github.com/ctrlshiftaltdel/AgentOrch/issues/71) | 验证真实 GitHub Release 下载、签名与已发布旧包升级 | #76 | 已完成 / `VERIFIED`（PR [#82](https://github.com/ctrlshiftaltdel/AgentOrch/pull/82) 合并 `4a7069e`；真实 v1.5 → v1.6 升级 `APPLIED`，Format 1.5 → 1.6、90/90 包内文件一致、项目自有文件不变；真实 1.3 / 1.4 资产与以 1.6 为已安装基线仍 `NOT_RUN`，签名校验 `NOT_APPLICABLE`） |
| [#72](https://github.com/ctrlshiftaltdel/AgentOrch/issues/72) | Windows / macOS 实机验证发行包与更新引擎 | 由 #77 收口 | 已完成 / `VERIFIED`（实现任务 #77 / PR [#79](https://github.com/ctrlshiftaltdel/AgentOrch/pull/79) 合并 `e26902f`；Issue 已关闭并标 `status:verified`；GitHub-hosted runner 之外的安装器 / 桌面环境与自托管平台仍 `UNKNOWN`） |
| [#85](https://github.com/ctrlshiftaltdel/AgentOrch/issues/85) | 下游项目有 `docs/` 时 1.6 包无法通过 `validate_kit` 与自带测试（含大小写路径残留） | #76 | 已完成 / `VERIFIED`（PR [#87](https://github.com/ctrlshiftaltdel/AgentOrch/pull/87) 合并 `72a39e4`；下游 `validate_kit` 与包内测试通过，`tree mode` 区分纯净包 / 下游 / 上游三态；Issue 已关闭并标 `status:verified`） |
| [#86](https://github.com/ctrlshiftaltdel/AgentOrch/issues/86) | 发布 AgentOrch 1.6.1（`AgentOrch-1.6.1.zip`，Format 1.6） | #85 | 已完成 / `VERIFIED`（PR [#88](https://github.com/ctrlshiftaltdel/AgentOrch/pull/88) 合并 `baa5c91`；[Release v1.6.1](https://github.com/ctrlshiftaltdel/AgentOrch/releases/tag/v1.6.1)，资产 SHA256 `7b70d722…`；Issue 已关闭并标 `status:verified`） |
| [#93](https://github.com/ctrlshiftaltdel/AgentOrch/issues/93) | `task add` 重复多值选项静默丢值修复（`--acceptance` / `--paths` / `--depends` / `--resources`） | 无阻塞依赖（1.6.1 后 bugfix） | 已完成 / `VERIFIED`（PR [#94](https://github.com/ctrlshiftaltdel/AgentOrch/pull/94) 合并 `35fb924`；重复出现改为合并保留，`--acceptance` 保序、`--paths` / `--depends` 仍排序去重，单次多值写法兼容；ready 前缀冲突、`VERIFIED` 必须带 note、approval SHA 不匹配拒绝、非法状态跳转拒绝 + events 四条安全行为未回归；测试 703 → 715；Issue 已关闭并标 `status:verified`） |
| [#95](https://github.com/ctrlshiftaltdel/AgentOrch/issues/95) | 发布 AgentOrch 1.6.2（`AgentOrch-1.6.2.zip`，Format 1.6 不变） | #93 | 已完成 / `VERIFIED`（PR [#96](https://github.com/ctrlshiftaltdel/AgentOrch/pull/96) 合并 `bab65b6`；[Release v1.6.2](https://github.com/ctrlshiftaltdel/AgentOrch/releases/tag/v1.6.2)，资产 SHA256 `096e1fba…`；真实 1.6.0 / 1.6.1 → 1.6.2 升级仍 `NOT_RUN`；Issue 已关闭并标 `status:verified`） |
| [#99](https://github.com/ctrlshiftaltdel/AgentOrch/issues/99) | 路径冲突事件 / M4 path 采集 / ready 独立事件 | 无阻塞依赖 | 已完成 / `VERIFIED`（PR [#109](https://github.com/ctrlshiftaltdel/AgentOrch/pull/109) 合并 `636572d`；写入已定义的 `CONFLICT_RECORDED`，`report_metrics` 采集 M4 path 冲突，`TASK_READY` 拆为独立事件；Issue 已关闭并标 `status:verified`） |
| [#100](https://github.com/ctrlshiftaltdel/AgentOrch/issues/100) | `task amend --paths`（阻塞后更新登记）原子重写路径与锁 | 无阻塞依赖 | 已完成 / `VERIFIED`（PR [#106](https://github.com/ctrlshiftaltdel/AgentOrch/pull/106) 合并 `6653acc`；阻塞任务可原子重写允许路径与路径锁；Issue 已关闭并标 `status:verified`） |
| [#101](https://github.com/ctrlshiftaltdel/AgentOrch/issues/101) | `check_scope.py` + G2 范围证据 + `REQUIRED` 90 → 92 | 无阻塞依赖 | 已完成 / `VERIFIED`（PR [#107](https://github.com/ctrlshiftaltdel/AgentOrch/pull/107) 合并 `c4b699e`；新增范围检查脚本与审查清单 G2 证据形态，`REQUIRED` 90 → 92；Issue 已关闭并标 `status:verified`） |
| [#102](https://github.com/ctrlshiftaltdel/AgentOrch/issues/102) | 澄清会话入口：kit 第三部分按需读 | 无阻塞依赖 | 已完成 / `VERIFIED`（PR [#105](https://github.com/ctrlshiftaltdel/AgentOrch/pull/105) 合并 `81df375`；三个入口统一回指 `AGENTS.md` 的阅读口径，第三部分触发条件不变；Issue 已关闭并标 `status:verified`） |
| [#103](https://github.com/ctrlshiftaltdel/AgentOrch/issues/103) | Risks 填写深度口径（不新增字段） | 无阻塞依赖 | 已完成 / `VERIFIED`（PR [#108](https://github.com/ctrlshiftaltdel/AgentOrch/pull/108) 合并 `4e8922e`；统一 G-2 / G-3 的 Risks 填写深度，未新增字段；Issue 已关闭并标 `status:verified`） |
| [#104](https://github.com/ctrlshiftaltdel/AgentOrch/issues/104) | 可选文档收口：P1-3 未覆盖范围 + O-1～O-3 口径 + metrics 同步 | 无阻塞依赖（与 #101 文件重叠时可协作） | 已完成 / `VERIFIED`（PR [#110](https://github.com/ctrlshiftaltdel/AgentOrch/pull/110) 合并 `51e418f`；收口 P1-3 与 O-1～O-3 文档口径并同步 metrics 数据来源；Issue 已关闭并标 `status:verified`） |
| [#113](https://github.com/ctrlshiftaltdel/AgentOrch/issues/113) | 发布 AgentOrch 1.6.3（`AgentOrch-1.6.3.zip`，Format 1.6 不变） | #99–#104（均已 `VERIFIED`） | 已完成 / `VERIFIED`（PR [#114](https://github.com/ctrlshiftaltdel/AgentOrch/pull/114) 合并 `2adf431`；[Release v1.6.3](https://github.com/ctrlshiftaltdel/AgentOrch/releases/tag/v1.6.3)，资产 461,829 bytes，SHA256 `dcce5b24…` 与 GitHub API `assets[].digest` 一致；真实 `1.6.2 → 1.6.3` 隔离升级 `APPLIED`，证据见 §12 与 `docs/upgrade.md` §14.5；Issue 已关闭并标 `status:verified`） |
| [#117](https://github.com/ctrlshiftaltdel/AgentOrch/issues/117) | Phase D S0 设计冻结：角色契约、能力分层、发现与降级、动态选型、终端私有记录 | 无阻塞依赖 | 已完成 / `VERIFIED`（PR [#118](https://github.com/ctrlshiftaltdel/AgentOrch/pull/118) 合并 `ceb2c0a`；设计文档 `docs/design/agent-role-discovery-and-model-selection.md`；Issue 已关闭并标 `status:verified`） |
| [#119](https://github.com/ctrlshiftaltdel/AgentOrch/issues/119) | Phase D Epic：汇总 #117、#125 与 S1–S5（#120–#124） | 汇总 #117、#125、#120–#124 | `OPEN` / 进行中（Epic；S1 #120 `VERIFIED`；S2 #121 进行中；#122–#124 `BLOCKED`） | Epic Issue；阶段顺序、依赖与出口见 §13 |
| [#120](https://github.com/ctrlshiftaltdel/AgentOrch/issues/120) | Phase D S1：每终端独立 scope 与 Markdown 私有记录基座 | #117、#125 | 已完成 / `VERIFIED`（PR #127 合并 `818adaa`；主分支验证 813 tests / 98 required / 58/58） | Issue 正文；§13 |
| [#121](https://github.com/ctrlshiftaltdel/AgentOrch/issues/121) | Phase D S2：Runtime adapter、Agent 发现与角色匹配 | #117、#120 | 进行中（PR 见 Issue #121 `ORCH-TASK-REGISTRY` 登记；依赖 #120、#125 已 `VERIFIED`） | Issue 正文；§13 |
| [#122](https://github.com/ctrlshiftaltdel/AgentOrch/issues/122) | Phase D S3：Artificial Analysis 官方数据源与角色专项动态选型 | #117、#120、#121 | `BLOCKED`（等待 #120–#121 `VERIFIED`） | Issue 正文；§13 |
| [#123](https://github.com/ctrlshiftaltdel/AgentOrch/issues/123) | Phase D S4：本机角色表现反馈与可解释校准 | #120–#122 | `BLOCKED`（等待 #120–#122 `VERIFIED`） | Issue 正文；§13 |
| [#124](https://github.com/ctrlshiftaltdel/AgentOrch/issues/124) | Phase D S5：入口集成与端到端合成回归 | #120–#123 | `BLOCKED`（等待 #120–#123 `VERIFIED`） | Issue 正文；§13 |

**Epic #46 收口与残留任务：** Epic [#46](https://github.com/ctrlshiftaltdel/AgentOrch/issues/46) 已按 `templates/milestone-audit.md` 于 2026-10-26 完成阶段审计并关闭（[审计评论](https://github.com/ctrlshiftaltdel/AgentOrch/issues/46#issuecomment-6415751115)），S0–S6 全部完成。审计 `BLOCKING` / `NEEDS_HUMAN_DECISION` 均为 0，登记的三项 `NON_BLOCKING_HARDENING` 中 [#71](https://github.com/ctrlshiftaltdel/AgentOrch/issues/71)、[#72](https://github.com/ctrlshiftaltdel/AgentOrch/issues/72) 已由后续任务收口（#71 → PR #82；#72 → #77 的跨平台 CI）；审计后的 [#85](https://github.com/ctrlshiftaltdel/AgentOrch/issues/85)、[#86](https://github.com/ctrlshiftaltdel/AgentOrch/issues/86) 也已 `VERIFIED`（#85 → PR #87；#86 → PR #88，发布 1.6.1），不属于审计硬化项；1.6.1 之后的 [#93](https://github.com/ctrlshiftaltdel/AgentOrch/issues/93)（PR #94，1.6.2 补丁）与 [#95](https://github.com/ctrlshiftaltdel/AgentOrch/issues/95)（PR #96，发布 1.6.2）同样已 `VERIFIED`，也不属于审计硬化项；1.6.2 之后的 [#99](https://github.com/ctrlshiftaltdel/AgentOrch/issues/99)–[#104](https://github.com/ctrlshiftaltdel/AgentOrch/issues/104) 六项（PR #105–#110）同样已 `VERIFIED`，它们是 1.6.2 之后的独立改进与文档收口批次，**不属于审计硬化项**，也不改变本审计结论。**只剩下列一项未完成、未验证，不属于本轮 `VERIFIED` 结论**：

| 遗留任务 | 交付重点 | 当前状态与依据 |
|---|---|---|
| [#73](https://github.com/ctrlshiftaltdel/AgentOrch/issues/73) | 拆分 delivery scenarios 场景实现为按组模块 | `OPEN`；审计第 10 节标 `NON_BLOCKING_HARDENING`；可维护性硬化，非正确性问题；尚未派发实施 |

首批经验落地（不是等未来采集机制完成后才处理）：
- TalkDND 的具体经验已拆至 [#55](https://github.com/ctrlshiftaltdel/AgentOrch/issues/55)：模块拆分后的兼容验证、共享状态全调用点审计、锁保护完整性、回滚后的最终状态、阶段化失败语义。
- AgentMgr 的具体经验已拆至 [#56](https://github.com/ctrlshiftaltdel/AgentOrch/issues/56)：契约优先、核心与具体 Runtime Adapter 解耦、MCP/REST 共用应用服务、Mock 与真实验证证据分离、失败 / 状态未知语义。
- 两项任务把来源案例转为项目无关规则和合成测试，不修改 TalkDND 或 AgentMgr 产品代码。

执行纪律：
- #47 契约未冻结前，不得开始依赖该契约的完整实现；隔离的只读探测可以先做，但不得形成不可逆设计承诺。
- #48 与 #49 只有在锁定路径不重叠时才可并行；两者共享 `docs/self-improvement/`、`scripts/validate_kit.py`、`scripts/build_release.py` 与 CI，当前按路径锁串行。#51 同理等待共享路径释放。
- #50 依赖架构检查与经验管线；#52 依赖安全更新引擎；#53 最终验收依赖所有实现合并。
- 每个任务都按现有任务状态、路径锁、证据矩阵、独立审查和当前 head 验证执行。Issue 关闭不等于阶段验证完成。
- 该能力不能覆盖或弱化现有核心协作契约；涉及权限 / 安全边界、锁与状态机、数据迁移、破坏兼容或不可逆行为时，必须保留人工决策门。

## 12. 发布事实（2026-10-27）：1.6.3 / Format 1.6

- **决定（2026-10-27）**：本次发布 `1.6.3`，Format 保持 `1.6`；资产名 `AgentOrch-1.6.3.zip`，tag `v1.6.3`。`tag_matches_format('v1.6.3', '1.6')` 为真，仍满足更新引擎的 `VERSION_MATCH`（major.minor = 1.6）。
- **理由**：本批是加法能力（#99 路径冲突事件与 M4 path 采集、#100 `task amend --paths`、#101 新增 2 个 `REQUIRED` 文件、#102–#104 文档口径），没有文件移动 / 改名 / 删除，`MANIFEST.json` schema 仍为 1；按 `release/README` §5「只增加能力、不改包格式时 Format 不变」，只升对外 Release 版本。
- **未选择 Format 升级**：本批没有新增格式字段、载体契约或布局变化，不需要 Format 升级及其迁移说明。
- **发布结果（已完成）**：[Release v1.6.3](https://github.com/ctrlshiftaltdel/AgentOrch/releases/tag/v1.6.3) 已于 2026-10-27 发布；tag `v1.6.3` → `2adf4319c5826f97c6c98b8fa401473115f9b76f`；资产 `AgentOrch-1.6.3.zip`，461,829 bytes，SHA256 `dcce5b242997ccac44ee1dea225ca13c2e9af6583dc6bca3d5bdc35acb046885`（与 GitHub API `assets[].digest` 一致）；主分支 CI run [40471657312](https://github.com/ctrlshiftaltdel/AgentOrch/actions/runs/40471657312) @ `2adf431` 四平台全绿。
- **发布后补证（已完成）**：从 Release 下载资产并复核 SHA256 已执行；真实 `1.6.2 → 1.6.3` 隔离升级为 `APPLIED`——`PLAN` 的 10 项包校验全 `PASS`，`APPLY` 后 Format 1.6 → 1.6、`MANIFEST.json` files 90 → 92、92/92 包内文件与目标包逐字节一致、项目自有 `docs/PROJECT.md` / `docs/PLAN.md` / `LOCAL-NOTES.md` SHA256 前后不变、备份 `required=true` / `verified=true`、head 前后不变；升级后项目 `validate_kit` 退出码 0（downstream 模式），包内 `unittest` 675 tests `OK`（skip 19）。详细记录见 `docs/upgrade.md` §14.5。
- **范围边界**：本节只覆盖 `1.6.2 → 1.6.3` 这一次真实升级；真实 `1.6.0` / `1.6.1` → `1.6.2`、真实 1.3 / 1.4 资产、真实断网 / 限速 / DNS、`HD-11`、非 GitHub-hosted 平台仍为 `NOT_RUN` / `UNKNOWN`，不得用本次结果替代。
- 当前 `main` 的 754 tests、92 个 `REQUIRED` 文件（发行包 93 = 92 + `MANIFEST.json`）与 58/58 场景即 `v1.6.3` 发布基线的属性；`v1.6.2` 的 715 tests、91 文件包与资产 SHA256 `096e1fba…` 保持为历史发布事实。

## 13. Phase D — Agent 角色发现、Subagent 能力考核与动态模型选型（2026-10-27）

**目标**：在真实运行时能力、候选 Agent / 模型证据与本机私有记录的基础上，为每个任务选择 Execution 与 Reviewer；能力缺失、数据过期或来源不可用时安全降级并如实报告。设计冻结见 [agent-role-discovery-and-model-selection.md](design/agent-role-discovery-and-model-selection.md)。

本阶段是增量能力：不改变任务状态机、路径 / 资源锁、G1–G6 合并门，也不改变 C1–C4 / C1–C8 的能力语义。这些定义仍只在 [kit/orchestration.md](../kit/orchestration.md) 与 [templates/runtime-capability.md](../templates/runtime-capability.md) 中，本节只引用不重述。

### 13.1 阶段顺序、交付与出口条件

| 阶段 | 承接 Issue | 交付 | 依赖 | 出口条件 |
|---|---|---|---|---|
| S0 设计冻结 | [#117](https://github.com/ctrlshiftaltdel/AgentOrch/issues/117) | 设计文档 `docs/design/agent-role-discovery-and-model-selection.md`、文档导航、`.local/README.md` 的用途 / 隔离 / 隐私说明 | 无 | PR [#118](https://github.com/ctrlshiftaltdel/AgentOrch/pull/118) 合并到主分支且主分支 `VERIFIED` |
| P 阶段计划登记 | [#125](https://github.com/ctrlshiftaltdel/AgentOrch/issues/125) | 本节与第 1 节的登记；不实现运行时逻辑 | S0 已 `VERIFIED` | #125 `VERIFIED`；此前 S1–S5 不得进入 `READY`，也不得开始实现 |
| S1 每终端 scope + Markdown store | [#120](https://github.com/ctrlshiftaltdel/AgentOrch/issues/120) | 每终端独立 scope 解析、路径安全校验、仅 Markdown 的读写接口与写入失败语义 | #117、#125 | scope 隔离、路径安全、Markdown-only、写入失败语义与对应测试证据齐备 |
| S2 Runtime adapter / Agent discovery / 角色匹配 | [#121](https://github.com/ctrlshiftaltdel/AgentOrch/issues/121) | 运行时适配接口、候选注册、C1–C4 门与角色匹配报告、缺角色提醒 | #117、#120、#125 | C1–C4 门先于任何排序、显式注册表回退可用、缺角色提醒与 fixture 测试齐备 |
| S3 Artificial Analysis 数据源 + 动态选型 | [#122](https://github.com/ctrlshiftaltdel/AgentOrch/issues/122) | 官方 Data API 适配、供应商无关数据对象、硬筛选与解释性排序、新鲜度与降级记录 | #117、#120、#121、#125 | 官方 API 条款 / 字段 / 配额核验、密钥处理、硬筛选优先于排序、离线 / 过期降级与 fixture 测试齐备 |
| S4 本机项目反馈 | [#123](https://github.com/ctrlshiftaltdel/AgentOrch/issues/123) | 按 scope 记录 Master / Execution / Reviewer 的项目内表现与可解释校准建议 | #120–#122、#125 | 每 scope Markdown、样本量与 coverage 口径、无跨 scope 读取、不自动切换模型 |
| S5 入口集成 + 端到端合成回归 | [#124](https://github.com/ctrlshiftaltdel/AgentOrch/issues/124) | 会话入口接线、正向与负向合成场景、场景注册与发行检查 | #120–#123、#125 | 正向 / 负向场景均覆盖、两个 edition 语义一致、场景注册与发行检查通过 |

表中不含当前状态：任务状态只写第 1 节（见 §10 维护规则）。

### 13.2 依赖图与启动门

```text
#117 (S0 设计冻结)
  └─ #125 (P 阶段计划登记)
       └─ #120 (S1)
            └─ #121 (S2)
                 └─ #122 (S3)
                      └─ #123 (S4)
                           └─ #124 (S5)
```

- 无环依赖链：#117 → #125 → #120 → #121 → #122 → #123 → #124。
- 链上叠加的依赖：#122 同时依赖 #120 与 #121；#123 依赖 #120–#122；#124 依赖 #120–#123。
- Epic [#119](https://github.com/ctrlshiftaltdel/AgentOrch/issues/119) 汇总 #117、#125 与 #120–#124；它不替代任何单任务的验收，也不单独构成门。

启动门：

- #125 自身须在 #117 / PR #118 合并并 `VERIFIED` 后才可派发；本节的登记动作不改变 #125 的状态。
- #125 `VERIFIED` 之前，S1–S5 不得进入 `READY`，也不得开始实现；#125 通过后由 Master 按上表依赖逐任务另行置 `READY` / 派发。
- 每个实现任务派发前仍须按自身允许路径重新核对最新 `main` 与开放 PR 的路径冲突。
- 本文件不声称 S1–S5 已开始或已完成；它们的真实状态只以任务载体上的证据为准。

### 13.3 阶段边界与失败处理

- 不改任务状态机、路径 / 资源锁、G1–G6、C1–C4 或 C1–C8；不新增角色级门禁，也不建立第二套证据定义。
- 只用 Python 3 标准库，不引入第三方依赖；基础 CLI 在离线条件下照常可用。
- Artificial Analysis 是可选适配器：不可用、限流或数据过期时不阻塞治理流程，相关数据如实标 `UNKNOWN` / `STALE` / `BLOCKED`，不冒充实时查询成功。
- `.local/agent-orch/<scope-id>/` 的记录不入 Git、不进发行包、不跨终端同步；不同 scope 之间不得互相读取或继承。
- Reviewer 与 Execution 必须使用不同底层模型 ID；不同模型别名、温度或系统提示词不算独立。
- 不自动切换模型、不自动授权、不自动创建 Subagent；无合格候选时停止自动选择并请求 Master / 用户决策。
- 失败保持 `BLOCKED` / `NEEDS_HUMAN_DECISION`，并写明缺失项与降级方式；登记动作本身不得把任何后续阶段置 `READY`。

### 13.4 与历史阶段 / 设计目标的关系

- Phase A / B / C 与 1.6.x 的发布 / 验收事实（第 1 节、§11、§12）原样保留；Phase D 是增量阶段，不改写历史数字与结论。
- [PLAN.md](PLAN.md) 仍是设计目标权威；本文件只登记阶段顺序、依赖与当前状态，状态只落在第 1 节。
- 本节与设计冻结文档或 `PLAN.md` 冲突时，停下对齐，不在两处各写一套。
