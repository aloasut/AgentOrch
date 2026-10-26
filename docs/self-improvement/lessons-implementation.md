# 教训记录、证据等级、状态机与去重（#49 实现记录）

> 契约语义权威：[`lesson-lifecycle.md`](lesson-lifecycle.md)；字段 / 枚举权威：[`../contracts/schemas/lesson.schema.json`](../contracts/schemas/lesson.schema.json)（均由 #47 冻结，本任务未修改）。
> 本文件只说明 #49 的**实现能力与边界**：实现了哪些判定、哪些留给人工、哪些无法用当前 schema 表达。契约与实现不一致时以契约与 schema 为准，并停下来登记缺陷。

## 1. 组件与入口

| 路径 | 职责 |
|---|---|
| [`scripts/self_improvement/lessons.py`](../../scripts/self_improvement/lessons.py) | 教训校验、四类内容 / E0–E4、T1–T12 状态机、`sha256-normalized-v1` 指纹、去重索引、冲突、报告渲染 |
| `scripts/self_improvement/untrusted.py` | 来源文本脱敏与指令形态识别（只计数） |
| `scripts/self_improvement/pipeline.py` | 扫描时按 `--analysis` 显式分析创建教训；无分析时只出候选与证据 |
| `scripts/self_improvement/cli.py` | `lesson list` / `lesson validate` |
| [`tests/self_improvement/test_lesson_lifecycle.py`](../../tests/self_improvement/test_lesson_lifecycle.py) | 指纹、四类内容、转换表、非法转换、冲突、去重、报告的正负 fixture |
| [`tests/self_improvement/test_pipeline.py`](../../tests/self_improvement/test_pipeline.py) | 跨扫描幂等、冲突报告、报告字段（证据链接 / 时间 / 游标） |

默认教训库：`.local/self-improvement/lessons.json`（git-ignored），可用 `--store` 覆盖。本实现**不创建 Issue、不生成任务、不采纳教训**。

## 2. 四类内容与证据等级

`ALLOWED_EVIDENCE_LEVELS` / `ALLOWED_STATUSES` 是 lesson-lifecycle.md §2.1 两个表格的代码投影，`validate_lesson` 直接按它们判定：

| `content_class` | 允许的证据等级 | 允许的状态 | 能否生成任务 |
|---|---|---|---|
| `CONFIRMED_FACT` | E1–E4 | `OBSERVED` / `NEEDS_VERIFICATION` / `VERIFIED` / `REJECTED` / `REGRESSION_WATCH` | 否 |
| `UNVERIFIED_ASSUMPTION` | E0–E1 | `OBSERVED` / `NEEDS_VERIFICATION` / `REJECTED` | 否 |
| `SOURCE_SPECIFIC_EXPERIENCE` | E1–E4 | `OBSERVED` / `NEEDS_VERIFICATION` / `VERIFIED` / `REJECTED` / `REGRESSION_WATCH` | 否 |
| `GENERAL_LESSON` | E2–E4 | `VERIFIED` / `GENERALIZED` / `IMPLEMENTED` / `REJECTED` / `REGRESSION_WATCH` | 仅 `GENERALIZED` 且无 `OPEN` 冲突 |

额外强制：

- `UNVERIFIED_ASSUMPTION` 的证据等级超过 E1 直接拒绝（不能靠改字段“升级”）。
- `SOURCE_SPECIFIC_EXPERIENCE` 的 `applicability.scope` 必须是 `source_only`；`GENERAL_LESSON` 必须是 `agentorch_general`。
- `VERIFIED` / `GENERALIZED` / `IMPLEMENTED` / `REGRESSION_WATCH` 需要 E2+。
- `REJECTED` / `GENERALIZED` / `IMPLEMENTED` 必须有 `decision`；`GENERALIZED` / `IMPLEMENTED` 还不得带 `OPEN` 冲突。
- 标题、观测、根因、影响、建议摘要中出现令牌形态或个人绝对路径 → 校验失败（不静默脱敏写入）。

## 3. 状态机（T1–T12）

| # | 转换 | 实现位置与守卫 |
|---|---|---|
| T1 | （新）→ `OBSERVED` | `build_lesson`：`evidence_urls` 非空 + 指纹当场计算，缺一不可 |
| T2 | `OBSERVED` → `NEEDS_VERIFICATION` | `transition` |
| T3 | `OBSERVED` → `VERIFIED` | 需 E2+ 且分类为 `CONFIRMED_FACT` / `SOURCE_SPECIFIC_EXPERIENCE` |
| T4 | `OBSERVED` / `NEEDS_VERIFICATION` → `REJECTED` | `decision.outcome=REJECT` |
| T5 | `NEEDS_VERIFICATION` → `VERIFIED` | 需 E2+ |
| T6 | `VERIFIED` → `GENERALIZED` | `decision.outcome=ADOPT` + 已是 `GENERAL_LESSON` + `scope=agentorch_general` + 无 `OPEN` 冲突 |
| T7 | `VERIFIED` → `REJECTED` | `decision` 必填 |
| T8 | `GENERALIZED` → `IMPLEMENTED` | `links.issues` 或 `links.pull_requests` 必填，`decision` 保留 |
| T9 | `IMPLEMENTED` → `REGRESSION_WATCH` | 必须给出观察窗口 / 检查方式；写入 `links.modules` 的 `window:<text>` |
| T10 | `REGRESSION_WATCH` → `NEEDS_VERIFICATION` | 必须带至少一个新证据链接 |
| T11 | 证据撤回后降级 | `demote()`：分类回 `UNVERIFIED_ASSUMPTION`、等级 E0/E1、状态 `OBSERVED`/`NEEDS_VERIFICATION`，`decision` 记录原因 |
| T12 | `GENERALIZED` → `VERIFIED` | 必须显式给 `content_class=CONFIRMED_FACT|SOURCE_SPECIFIC_EXPERIENCE` + `decision`；`scope` 自动回 `source_only` |

非法转换（§3.3）逐条拒绝并给出原因：跳过验证直接 `GENERALIZED`/`IMPLEMENTED`；`UNVERIFIED_ASSUMPTION` → 任意结论态；`SOURCE_SPECIFIC_EXPERIENCE` → 通用态（必须先显式 `reclassify()` 并记录决策）；`REJECTED` 之后任何转换（终局）；带 `OPEN` 冲突进入 `GENERALIZED`/`IMPLEMENTED`；结论态缺 `decision`；把 `NOT_RUN`/`UNKNOWN`/`BLOCKED`/`PARTIAL` 的采集状态当作已验证。

分类变化是显式操作：

```python
lessons.reclassify(record, 'GENERAL_LESSON', decision=lessons.make_decision(...))
lessons.demote(record, reason='来源证据链接已失效', decided_by='project-owner')
```

## 4. 指纹 `sha256-normalized-v1`

规范化严格按 lesson-lifecycle.md §4.1 的七步执行：NFKC → `casefold()` → 空白折叠 → 去首尾空白 → 去结尾标点（`. , ; : ! ? 。 ， ； ： ！ ？`）→ `affected_surface` / `suggested_action_target` 只保留 `[a-z0-9_./-]` 并再次折叠空白 → 空字段按空字符串。摘要使用固定的 canonical JSON（字段名排序、`ensure_ascii=False`、紧凑分隔符），输出 64 位小写十六进制。

`normalized_fields` 至少三个且只能来自 `root_cause` / `impact` / `affected_surface` / `suggested_action_target`。schema 没有专门的 `affected_surface` 字段，因此实现按下述规则从现有字段派生（这是实现决定，不是契约改动）：

| 指纹字段 | 取值来源 |
|---|---|
| `root_cause` | `observation.root_cause` |
| `impact` | `observation.impact` |
| `affected_surface` | `applicability.applies_to` 排序后用 `|` 连接的字符串 |
| `suggested_action_target` | `suggested_action.target` |

`validate_lesson` 会**重算**指纹并与记录中的 `value` 比较：手改指纹、改根因却不重算，都会被拒绝（§9“记录缺字段 / 算法不可用 → 拒绝写入”）。

## 5. 去重、冲突与候选

`LessonStore` 维护三个索引，`ingest()` 按以下顺序判定：

| 情况 | 结果 | 动作 |
|---|---|---|
| 同一 `(source_id, evidence_url, fingerprint)` | `idempotent` | 不写第二条、不改时间戳 |
| 指纹相同、证据链接不同 | `duplicate` | 证据合并进最早 `lesson_id`，`captured_at`/`updated_at` 前移；结果带 `duplicate_of`；**不产生**第二个 lesson / Issue |
| 证据链接相同、指纹不同（根因描述被修正） | `fingerprint_updated` | 在同一 `lesson_id` 上更新 `title`/`observation`/`applicability`/`suggested_action` 与指纹；旧指纹仍解析到同一 `lesson_id` |
| 证据链接相同但 `content_class` / `status` 不同 | 拒绝 | 提示改用 `reclassify()` / `transition()`，避免用“第二份分析”绕过状态机 |
| 其余 | `created` | 分配 `LSN-<SOURCE>-NNN`，序号不复用 |

冲突：

- `make_conflict()` 默认 `resolution=OPEN`；`add_conflict()` 不会自动选边。
- `GENERALIZED` / `IMPLEMENTED` 记录不允许**新增** `OPEN` 冲突（schema 的 `allOf` 直接禁止）。发现新冲突时先把它挂到已验证记录上，或将通用记录按 T12 退回后再处理。
- 解除只允许 `RESOLVED_BY_EVIDENCE` / `RESOLVED_BY_OWNER`，且必须给 `resolution_evidence`；否则拒绝。
- `can_generate_task()` 只在 `GENERAL_LESSON` + `GENERALIZED` + 无 `OPEN` 冲突 + 非 duplicate 时返回真。

候选与教训分离：采集产出的是**候选指针**（`candidate_from_evidence`），只有提供显式分析（标题、分类、等级、观测、适用性、建议动作）才能 `draft_lesson()`。没有根因分析时不会用标题占位，因为占位根因会让不同发现撞进同一指纹——§9 明确禁止退化为“标题匹配去重”。

## 6. 报告输出

`pipeline.run_scan` → `lessons.build_report`，同时写 JSON 与 Markdown：

- 顶部固定写入 `untrusted_data` 声明：`content_trust=untrusted_data`、`may_override_rules=false`、`redaction_required=true`。
- 每个来源：`scan_started_at` / `scan_finished_at` / `window{mode,since,until}` / `cursor_before` / `cursor_after` / `missing_evidence` / `truncated` / 证据链接。
- 每条教训：`lesson_id`、分类、状态、证据等级、`evidence_urls`、`observed_at` / `captured_at`、指纹、`duplicate_of`、冲突及 `OPEN` 列表、能否生成任务及阻塞原因。
- `counts`：来源各状态、证据条数、排除数、可疑指令数、教训按分类 / 状态计数、重复数、`OPEN` 冲突数、可生成任务数。
- `decisions_required`：游标倒退、`authorized_private` 来源不可读（`HD-01`）、`OPEN` 冲突（`HD-04`）。
- Markdown 中所有来源文本经 `untrusted.data_cell`：换行压平、反引号中性化、加 `data:` 前缀；指令形态文本只出现在数据列与计数里。

报告本身是只读产物，不修改注册表、教训库或来源仓库（扫描由 `--dry-run` 控制是否持久化游标）。

## 7. 限制与未验证项

- **没有任何真实教训记录。** 验收用一个合成 fixture 覆盖四类内容与状态转换；本任务没有从 TalkDND / AgentMgr 提炼出真实教训，也不声称已提炼。
- 状态机的“语义守卫”只覆盖可机器判定的部分：根因是否真的成立、结论是否真的与来源业务无关、`E2` 复现是否可靠，仍需审查者判断（lesson-lifecycle.md §3.3 也这么规定）。
- **T10 与 schema 存在一处张力**：`GENERAL_LESSON` 的允许状态不含 `NEEDS_VERIFICATION`，因此对通用教训执行 `REGRESSION_WATCH → NEEDS_VERIFICATION` 会被校验拒绝。当前实现要求先按 T12 退回 `CONFIRMED_FACT` / `SOURCE_SPECIFIC_EXPERIENCE` 再进入 `NEEDS_VERIFICATION`；这是对冻结契约的解释，不是新状态，已登记为审查注意项。
- `decision.decided_by` 必须是具体决策人 / 角色（不能写 `team`），但实现无法验证字符串背后是否真有其人；这是流程约束，不是代码保证。
- 指纹只做规范化后的精确匹配：同义改写会产生不同指纹（契约有意的保守选择）。近似重复仍需人工按 `OVERLAPS` 处理，本实现不自动合并。
- 教训库是本地 JSON（`.local/self-improvement/`），不是数据库；并发写入未实现，同一工作区同一时刻只应有一个写入者。
- 不自动创建 Issue / 任务、不自动采纳、不关闭任何 Issue；`IMPLEMENTED` 必须由人写入任务编号。

## 8. 本机真实验证（#49 分支，Python 3.13.5）

```bash
python3 -m unittest tests.self_improvement      # 退出码 0
python3 -m unittest discover -s tests           # 退出码 0
python3 scripts/self_improvement/cli.py lesson list
python3 scripts/self_improvement/cli.py lesson validate --file <lessons.json>
python3 scripts/validate_kit.py                 # 退出码 0
```

`lesson list` / `lesson validate` 在空库和合成文件上的实际输出见 PR 评论的证据矩阵；未运行的命令不得写成已验证。
