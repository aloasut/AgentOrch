# Implementation Plan

> 这是模板：复制到项目根目录后再编辑（`python scripts/orchestrator.py init` 会自动逐字节复制）；不要直接修改本模板，复制后可删除本段说明。
> 项目根目录的 `PLAN.md` 是计划权威——任务登记、派发与阶段收口都以它为准；本模板只用于初始化复制。

> This plan is the source for task registration. Each Task block below must translate field by field into one `task add` command; split any block that fails the granularity check instead of registering it.
> Acceptance criterion ids and the structured scenario fields are defined once, in `AGENT-ORCHESTRATION.md` 4.1; the plan only decides numbering and applicability, it does not restate the rules.

## Plan header

- **Plan name:**
- **Source charter / design doc:**
- **Overall goal:**

## Single-goal check (run before registering each block)

- [ ] The block names exactly one independently acceptable goal; if two outcomes can be accepted separately, split the block.
- [ ] The `Goal` line holds one outcome sentence — no chained deliverables ("and also", "plus", "then").
- [ ] Every acceptance criterion carries a unique `AC-<n>` id and states one checkable fact.
- [ ] The AC ids written here are the ones the Execution Agent must reuse in `ac_id` of the task packet evidence matrix; renaming an AC after dispatch is not allowed.
- [ ] Known scenario fields (`invariants`, `negative_cases`, `migration_cases`, `integration_paths`, `unverified_assumptions`) are either listed below or explicitly deferred to the task packet with a reason; a migration-shaped task must not silently drop `migration_cases`.

## Task blocks

<!-- Repeat the block below for every task in the plan. Keep blocks in dependency order. -->

### Task: <Task ID>

- **Task ID:**
- **Goal:**
<!-- Exactly one independently acceptable goal. If the block holds more than one acceptable goal, split it before registration. -->
- **Allowed paths:**
<!-- Precise down to concrete files or directories; must match the --paths lock exactly. -->
- **Validation:**
<!-- Verification commands with their expected output. -->
  - Command:
  - Expected output:
- **Acceptance criteria:**
<!-- Every criterion must be individually checkable, numbered AC-1, AC-2, ... -->
  - [ ] AC-1:
- **Known scenario fields:**
<!-- Optional at plan time: name the scenarios already foreseeable (invariants / negative cases / migration cases / integration paths / open assumptions); the task packet fills the five fields and writes "N/A: <reason>" when a field truly does not apply. -->
  - Invariants:
  - Negative cases:
  - Migration cases:
  - Integration paths:
  - Unverified assumptions:
- **Depends on:**
<!-- Task IDs that must be VERIFIED before this task can start. Write "none" if there are no dependencies. -->
