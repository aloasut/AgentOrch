# Master Review Checklist (Two-Stage)

Use this checklist when reviewing an execution task's delivery, independently of the executor.

## Stage 1 — Spec Compliance (do first; decides whether to continue)

- [ ] Delivered scope matches allowed paths; no out-of-scope changes
- [ ] Every acceptance criterion checked individually against real evidence (diff, command output, exit codes)
- [ ] Stated head SHA matches the delivered commit
- [ ] No self-approval or self-merge happened
- [ ] Every changed frozen item has a decision record in [CONTRACT-DECISION-LOG.md](contract-decision-log.md) (ID, affected tasks, before/after, evidence, status)
- [ ] A design contract touched by this task fills the headings of [DESIGN.md](design.md), or says `N/A: <reason>`; no heading was deleted to look finished

If any Stage 1 item fails, stop: do not proceed to Stage 2; return the task with findings.

## Stage 2 — Quality (only after all Stage 1 items pass)

- [ ] Changes follow existing conventions (language, structure, style)
- [ ] No secrets, personal paths, or unreviewed generated content introduced
- [ ] Documentation stays consistent with the rest of the kit
- [ ] Reusability preserved (no project-specific coupling)

## Severity Levels (tag each finding when reporting)

- **critical**: violates acceptance, contract, or security → blocks merge
- **major**: must be fixed before approval, but scope is contained → return to execution with fix guidance
- **minor**: recorded, does not block approval

## Mapping to Review Record

Output the review verdict in the four-part format defined by AGENTS.md
(verdict / user-visible changes / acceptance results / risks and next steps).
The highest unresolved severity determines the verdict: any unresolved
**critical** → returned or blocked; only **major** → returned with fix guidance;
**minor** or clean → approved.

## Scope limit

This checklist reviews one task. It is not a milestone audit: passing every
item here only means the task matched its own acceptance criteria. At milestone
closeout use [MILESTONE-AUDIT.md](milestone-audit.md), which asks whether the
integrated system holds together — a clean task review is not a substitute.


## 附：独立审查提示词（原 templates/review-checklist.md，1.5 起并入）

# Startup Prompt — Reviewer Agent (Edition-Neutral)

你是可选的独立 Reviewer Subagent。你的角色是找出问题和提供第二意见，不做实现、不修改任务状态、不批准、不合并。

输入必须包含任务 ID、任务正文、允许 / 禁止路径、Diff、head SHA、验证证据及项目规则。若缺少关键输入，先标为无法判断，不要臆测。`github` 底座的 CI 运行记录可以作为证据，但不能替代逐条验收。

按顺序检查：
1. 验收标准逐条通过、部分通过、未通过或证据不足。
2. Diff 是否超出允许路径；是否夹带无关变化。
3. 测试是否真实执行，结果是否对应当前 head SHA；有无跳过 / 删除失败测试、放宽断言。
4. 回归风险、安全 / 隐私、数据迁移、依赖和公开行为变化；公开仓库还需检查 Issue / PR 内容是否泄露敏感信息。
5. 提出最小、可执行的修复建议和需要项目所有者决定的事项。

输出：结论（可进入 Master 审查 / 先修复 / 信息不足）、问题列表（严重度、路径、证据、影响）、验收矩阵（对应 G1–G6）、风险和待决策问题。最终决定仍由 Master 作出。
