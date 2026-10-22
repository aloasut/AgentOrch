# Implementation Plan — AgentOrch

> 本文件是本仓库的计划权威：任务登记、派发与阶段收口都以它为准；`templates/PLAN.md` 只用于初始化复制，不是本项目的计划。
> 验收字段、证据矩阵与场景字段的定义只在 `AGENT-ORCHESTRATION.md` 4.1；本文件只决定编号、顺序与适用性，不重述规则。

## Plan header

- **Plan name:** AgentOrch 可靠性交付升级（Epic #1）
- **Source charter / design doc:** [docs/PROJECT-CHARTER.md](docs/PROJECT-CHARTER.md)、[docs/AGENTORCH_IMPROVEMENT_PLAN_2026-10.md](docs/AGENTORCH_IMPROVEMENT_PLAN_2026-10.md)、[Epic #1](https://github.com/ctrlshiftaltdel/AgentOrch/issues/1)
- **Overall goal:** 把“任务证据、阶段审计、资源锁、套件漂移、运行时能力”变成可逐条验证的交付能力，并在当前 `github` 底座上用 Issue / PR / CI 留下证据。

## 基线与当前状态（2026-10-22）

| 里程碑 | 内容 | 状态 | 依据 |
|---|---|---|---|
| Phase A 前置 | 结构化验收证据矩阵与负向场景字段（#2） | 已完成 | Issue #2 已关闭，字段契约落在 `AGENT-ORCHESTRATION.md` 4.1 |
| Phase A 前置 | edition 权威来源与 fail-closed（#4） | 已完成 | Issue #4 已关闭；`ORCHESTRATION-PROJECT.md` 的 `edition` 为唯一权威 |
| 工程底座 | GitHub Actions 接入（#14） | 已完成 | Issue #14 已关闭；PR 上跑规则包校验、单元测试与语法检查 |
| 计划权威 | 根目录 `PLAN.md` 与 `init` 初始化（#15） | 本 PR 交付，待独立审查 | 本文件；`init` 冒烟与单元测试 |
| 发布门前置 | edition 旧格式升级说明（#13） | 待开始 | Issue #13 |
| 发布门前置 | 发布自检纳入 CI（#17） | 待开始（依赖 #14，已满足） | Issue #17 |

已关闭的 Issue 只代表交付完成，不等于本计划行已验证；每条交付仍以对应 PR 的 AC 逐条结果与合并后主分支重跑为准。

## 路线与顺序

### Phase A — 契约和验收基础

- #5 冻结共享资源锁契约（锁类型、所有权、租约、恢复语义）。设计冻结任务，产出契约而非实现。
- #3 设计契约冻结与阶段收口审计模板（可在 #2 之后起草，与 #5 的契约口径对齐后定稿）。

出口：资源锁契约覆盖并发、崩溃、租约过期、强制解锁与恢复；#3 的模板能列出阻断项、非阻断加固、可选增强与待人工决策项。

### Phase B — 调度、漂移和能力可观测性

- #6 按 #5 冻结的契约实现具名资源锁与冲突诊断，保持既有路径锁向后兼容。
- #7 发行包版本清单与下游核心规则漂移诊断（只读，不覆盖目标仓库）。
- #8 运行时能力登记与交付质量度量（能力、新鲜度、指标口径、缺失数据）。

出口：锁竞争不产生半套锁、重复所有权或静默释放；漂移诊断只读；能力与指标区分支持 / 不支持 / 未知 / 过期并链接真实证据。

### Phase C — 合成回归与发布验收

- #9 四类合成回归场景（治理 / 授权、迁移 / 版本、跨模块闭环、编排底座与证据失效）并集成通用验收程序。

出口：正向控制组与负向失败组都可重复运行；旧 SHA、证据缺失、锁冲突、待人工决定项不会被误报为 `VERIFIED`。

### 发布门前置（与 Phase B / C 并行）

- #13 补齐 edition 旧格式升级说明。
- #17 把 `scripts/build_release.py` 自检纳入 CI。

两者都必须在下一次发布之前完成；发布仍以 `python scripts/build_release.py` 自检 a–f 通过为准。

## 执行顺序（依赖已满足才可派发）

1. #5（Phase A，设计冻结）
2. #3（Phase A，模板与契约口径对齐）
3. #6（Phase B，依赖 #5）
4. #7 与 #8（Phase B，可并行，路径不重叠）
5. #9（Phase C，依赖 #2 / #3 / #4 / #5，最终验收等 #6–#8）
6. #13 与 #17（发布门前置，可与 Phase B / C 并行）

## 任务块登记规则

- 每个任务块的 `Goal` 只写一个可独立验收的结果；拆不动就继续拆，不得把多个目标塞进一个 Issue。
- `Allowed paths` 由任务包 / Issue 正文冻结并在派发时锁定；本计划只决定顺序与依赖，不改写路径锁。
- 验收项在任务包里编号为 `AC-1…AC-n`，派发后不得改名；证据矩阵逐条回填。
- 派发前检查依赖是否已 `VERIFIED`（`github` 底座以 Issue 关闭 + 合并后验证记录为准），未满足则停在 `PLANNED`。
- 阶段收口不以“子 Issue 全部关闭”为完成标准，按 `docs/AGENTORCH_IMPROVEMENT_PLAN_2026-10.md` 第 8 节做 Milestone Audit。

## 计划维护

- 本文件只经任务分支 + PR 修改；不得在会话里口头改计划而不落文件。
- 新任务先写进本文件再登记 Issue；关闭或取消的任务保留行并注明结果，不删除历史。
