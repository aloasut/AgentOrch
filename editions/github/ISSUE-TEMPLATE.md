# ISSUE-TEMPLATE.md — github 底座任务单

每个 Issue 的正文按下列五节填写。五节与 `local` 底座的任务包字段一一对应，缺任一节不得进入 `READY`。字段名与判定规则只在 `AGENT-ORCHESTRATION.md` 4.1 节定义，本模板只说明证据放在哪里、如何取回。

## 目标

- 单一、可验收的目标（一句话；出现第二个可独立验收的结果就拆 Issue）。
- 背景与用户可感知的结果。
- 明确不包含的内容（非目标）。

## 验收标准

- 逐条编号为 `AC-1`、`AC-2`……；派发后编号不再改写，新增标准用新编号。
- 每条都要能在当前 head 上判定通过 / 不通过，并且至少映射一条 evidence item。
- 部分通过不算通过；`NOT_RUN` / `BLOCKED` 不得折算为通过。

**证据矩阵**（贴在 Issue 正文或该 Issue 的 PR 评论，两者等价，`evidence_ref` 指向实际位置）：

| ac_id | method | expected | actual | status | environment | commit_sha | evidence_ref | notes |
|------|--------|----------|--------|--------|-------------|------------|--------------|-------|
| `AC-1` | 命令 / 测试 / 人工检查 | 期望结果 | 实际结果 | `PASS`（其余取值见 4.1 节） | 运行时与版本、底座、分支 | 等于矩阵 head SHA 的完整 commit | PR 评论 / CI 日志 / Diff 路径 | 备注；`NOT_APPLICABLE` 必填理由 |

- 矩阵必须声明一个 head SHA（= PR 最新 commit）；head 变化后重新取证，旧行只能作为历史。
- 列顺序固定（与 `local` 任务包一致）：`ac_id`、`method`、`expected`、`actual`、`status`、`environment`、`commit_sha`、`evidence_ref`、`notes`；字段含义与判定规则见 `AGENT-ORCHESTRATION.md` 4.1 节。
- 结构检查：`python scripts/validate_kit.py --task-packet <填好的任务包路径>` 是本地等价物；PR 评论里的矩阵必须与任务包字段同名同义。

**结构化场景字段**（与 `local` 任务包同名同义，含义见 `AGENT-ORCHESTRATION.md` 4.1 节）：`invariants`、`negative_cases`、`migration_cases`、`integration_paths`、`unverified_assumptions`。

小任务允许写 `N/A: <理由>`；留空或只写 `N/A` 视为字段缺失，不得进入 `READY`。

## 可改路径

- 完整列出允许修改的文件或目录。
- 路径粒度与该任务实际改动一致；不要用整个仓库兜底。
- 与 `ORCH-TASK-REGISTRY` 的 `locked_paths` 完全一致。

## 禁改路径

- 列出本任务禁止改动的文件或目录；未列出的路径默认仍受项目级禁改清单约束。
- 写明是否需要人工批准才能扩大范围。

## 依赖

- 列出必须先达到 `VERIFIED` 的 Issue 编号。
- 写明依赖的完成判据（合并 + 主分支验证）。
- 无依赖时写“无”。

---

标签建议：`status:ready`、`status:in-progress`、`status:review`、`status:blocked`，以及类型标签（`type:feature`、`type:fix`、`type:docs`、`type:chore`）。状态标签必须与 `ORCH-TASK-REGISTRY` 的 `status` 保持一致。
