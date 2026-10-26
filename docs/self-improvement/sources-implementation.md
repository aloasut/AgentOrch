# 经验来源注册表与采集适配器（#49 实现记录）

> 契约语义权威：[`sources-and-trust.md`](sources-and-trust.md)；字段 / 枚举权威：[`../contracts/schemas/source-registry.schema.json`](../contracts/schemas/source-registry.schema.json)（均由 #47 冻结，本任务未修改）。
> 本文件只说明 #49 的**实现能力与边界**：实际能证明什么、不能证明什么、如何运行。契约与实现不一致时以契约与 schema 为准，并停下来登记缺陷。
> 发行包 `REQUIRED` 清单、`build_release.py`、CI 与 `docs/README.md` 计数由 #52 统一接入；本任务不声明已随包发布。

## 1. 组件与入口

| 路径 | 职责 |
|---|---|
| [`scripts/self_improvement/sources.py`](../../scripts/self_improvement/sources.py) | 唯一权威注册表：读取、schema 子集 + 语义校验、新增 / 停用 / 启用 / 移除、扫描窗口与游标推进 |
| [`scripts/self_improvement/collect.py`](../../scripts/self_improvement/collect.py) | 只读采集适配器：`gh api --method GET`、字段提取、脱敏、失败分类、过滤与证据缺口标记 |
| [`scripts/self_improvement/untrusted.py`](../../scripts/self_improvement/untrusted.py) | 来源文本的数据化处理：脱敏、指令形态识别（只计数，不执行）、Markdown `data:` 渲染 |
| [`scripts/self_improvement/pipeline.py`](../../scripts/self_improvement/pipeline.py) | 一次扫描的编排：注册表 → 采集 → 教训 → 报告；扫描不持久化游标，调用方决定是否保存 |
| [`scripts/self_improvement/cli.py`](../../scripts/self_improvement/cli.py) | 命令行：`registry show/validate/add/disable/enable/remove`、`scan`、`lesson list/validate` |
| [`docs/self-improvement/sources.json`](sources.json) | 默认来源注册表：`talkdnd`、`agentmgr`，均为 `enabled=true`；2026-10-26 首轮真实扫描后 `scan_cursor` 为 `PARTIAL`（未推进成功水位，见 §10） |
| [`tests/self_improvement/test_registry.py`](../../tests/self_improvement/test_registry.py) | 注册表结构 / 配置操作 / 游标与窗口的正负 fixture |
| [`tests/self_improvement/test_collection.py`](../../tests/self_improvement/test_collection.py) | 合成 `gh` 响应：不可达、403 / 404 / 429、超时、坏 JSON、注入、脱敏、过滤、CI 缺口 |

全部实现仅用 Python 标准库；采集只通过注入的 runner 发起，测试不需要网络、凭据或 `gh`。

## 2. 注册表定位与失败语义

默认路径 `docs/self-improvement/sources.json`，可用 `--registry` 覆盖。注册表是**项目配置**，不是发行包内容。

| 情况 | 行为 |
|---|---|
| 文件缺失 / 不可读 / 不是 JSON | **失败关闭**：报配置错误并停止采集，退出码 `1`；不补默认来源 |
| `schema_version` 不是 `1.0` | 失败关闭，报实际值与支持版本，提示升级注册表或工具；不做降级猜测 |
| 任一来源非法（缺字段 / 非法枚举 / 非法 `source_id` / 重复 `source_id` / 未知字段 / 含凭据或个人路径） | **整份注册表拒绝加载**，不做部分接受；错误逐条给出 JSON 路径 |
| `sources: []` | 合法：报告“无来源可扫描”，退出码 `0`；不视为错误、不自动创建任务 |
| `enabled: false` | 合法：不扫描，报告 `NOT_RUN` + `disabled`；已形成的教训与决策记录保留 |

`repository` 只接受裸 `owner/repo`：URL、`git@`、CLI 参数、空格或 `@` 一律拒绝。`trust` 的四个常量（`untrusted_data` / `evidence_only|synthetic_fixture_source` / `redaction_required=true` / `may_override_rules=false`）按 schema 校验，不能按来源放宽。

## 3. 新增 / 停用 / 移除（纯配置，不改程序分支）

来源列表只在 `sources.json` 中，代码里没有 `talkdnd` / `agentmgr` 之类的分支。四个操作都只改数据，然后重新校验整份注册表：

```bash
# 新增（同时可加 --include / --exclude 过滤与 --disabled）
python3 scripts/self_improvement/cli.py registry add \
  --source-id acme --repository acme/app \
  --evidence-scope pull_request,issue,commit --lookback-days 30

# 停用 / 重新启用（保留条目与历史）
python3 scripts/self_improvement/cli.py registry disable --source-id acme
python3 scripts/self_improvement/cli.py registry enable  --source-id acme

# 移除（删到空数组也合法；已形成的教训与决策记录不删）
python3 scripts/self_improvement/cli.py registry remove --source-id acme
```

- 同一个 `source_id` **不得改指向**其它仓库：`add` 会拒绝并提示“新增来源 + 停用旧来源”。
- 移除来源只影响后续扫描；历史报告中的 `source_id` 仍可追溯（见 [lesson-lifecycle.md](lesson-lifecycle.md) §8）。
- 未经项目所有者批准不得登记 `access_mode=authorized_private`（`HD-01`）；本实现不会读取、请求或保存任何凭据，`gh` 使用其自身已有的认证，缺失或无权时降级为 `BLOCKED`。

## 4. 首次 / 增量扫描窗口与游标

`scan_cursor=null` = 从未尝试扫描。窗口按以下顺序决定（`sources.scan_window`）：

| 游标状态 | `mode` | `since` |
|---|---|---|
| `null` | `first_scan` | `now - lookback_days` |
| `last_scan_status=OK` 且有成功水位 | `incremental` | 上次 `last_successful_scan_at` |
| 非 `OK` 但有历史成功水位 | `retry` | 上次 `last_successful_scan_at` |
| 非 `OK` 且无成功水位（含游标丢失 / 首次失败） | `lookback_after_failed_scan` | `now - lookback_days` |

- 只有 `OK` 推进 `last_successful_scan_at` / `last_scanned_commit`；`PARTIAL` / `BLOCKED` / `UNKNOWN` 只记录本次状态与原因，成功水位保持不变。
- `OK` 必须有 40 位小写十六进制 `last_scanned_commit`；没有可定位的提交 SHA 时不会写 `OK`（`PARTIAL` + `watermark_not_in_scope`，或 `UNKNOWN` + `no_commit_watermark`）。
- `BLOCKED` / `UNKNOWN` 必须带 `blocked_reason`，缺理由直接拒绝写入。
- 本次 `last_scan_started_at` 早于注册表已有值 = **游标倒退**：不写新游标、不推进水位，报告 `UNKNOWN` + `cursor_regressed` 并产生 `NEEDS_HUMAN_DECISION:cursor_regression`，下一次按回溯窗口重扫。
- 重扫同一窗口是允许的：幂等由教训指纹保证（见 [lessons-implementation.md](lessons-implementation.md) §5），不在采集层去重。

## 5. 采集适配器能力

命令只由 `collect.build_command` 生成，形态固定为 `gh api --method GET <path>`，不经过 shell，不接受 `POST` / `--field` / `--input`。按来源的 `evidence_scope` 逐类读取：

| `evidence_kind` | 只读端点 | 保留字段 |
|---|---|---|
| `pull_request` | `repos/{repo}/pulls?state=all&sort=updated&direction=desc` | URL、标题、状态、`merged_at`、head SHA、labels |
| `issue` | `repos/{repo}/issues?state=all&since=…` | URL、标题、状态、labels（跳过 `pull_request` 行） |
| `review` | `repos/{repo}/pulls/comments?since=…` | URL、PR 编号摘要、`commit_id` |
| `commit` | `repos/{repo}/commits?since=…` | URL、首行提交信息、提交时间、SHA |
| `ci_run` | `repos/{repo}/actions/runs?created=%3E%3D…` | URL、工作流名 + 状态摘要、`head_sha`、结论 |

**不下载、不保存**：PR / Issue 正文、review 正文、diff 内容、CI 日志、提示词、完整会话。报告只保留可定位链接、结构化元数据与独立撰写的摘要，符合 sources-and-trust.md §3.2–§3.3。

每条证据会被脱敏（令牌形态、`/home/...`、`/Users/...`、`C:\Users\...`）并做指令形态识别；证据链接只接受 `http(s)` 且不含空白 / `<>` / 反引号，不合格时清空链接并标 `invalid_evidence_url`（避免注入报告 Markdown）；识别结果只是报告里的计数与链接，文本本身以 `data:` 字段呈现，**不会**被执行、转述为任务指令或扩大允许路径。

## 6. 失败映射

| 观察 | 扫描状态 | `blocked_reason` | 游标 |
|---|---|---|---|
| HTTP 404 / Not Found | `BLOCKED` | `not_found` | 不推进 |
| HTTP 403 / Forbidden / Resource not accessible | `BLOCKED` | `forbidden` | 不推进 |
| HTTP 429 / rate limit | `BLOCKED` | `rate_limited` | 不推进（不重试到成功） |
| 连接 / DNS / 代理失败 | `BLOCKED` | `network_unavailable` | 不推进 |
| `gh` 可执行文件缺失（`FileNotFoundError` / 127） | `BLOCKED` | `tool_unavailable` | 不推进 |
| 响应不是合法 JSON / 结构异常 | `UNKNOWN` | `malformed_response` | 不推进 |
| 命令超时 | `UNKNOWN` | `timeout` | 不推进 |
| 其它非零退出 | `UNKNOWN` | `unexpected_command_failure` | 不推进 |
| 部分类别失败，其余成功 | `PARTIAL` | `null`（缺失类别写入 `missing_evidence`） | 不推进 |
| 分页达到上限仍有更多数据 | `PARTIAL` | `null`（`truncated` 列出类别） | 不推进 |

补充规则：

- 全部类别都失败 → 取首个失败的原因；`BLOCKED` 与 `UNKNOWN` 不混用（全部为未知原因时记 `UNKNOWN`）。
- 未声明的 `evidence_kind` 不读取；`ci_run` 不在 `evidence_scope` 时，合并 PR 标记 `ci_not_in_scope` 而不是“CI 通过”。
- 已合并且无对应 `head_sha` 的 CI 运行 → 证据项标记 `missing_ci_evidence`；关闭但无合并证据 → `closed_without_merge_evidence`。这些是**缺口标记**，不会被推断成“已修复”。
- `--offline` 与 `enabled=false` 一律 `NOT_RUN`，报告 `offline` / `disabled`，不写游标。

## 7. 过滤

`inclusion_filters` / `exclusion_filters` 是 `kind:value` 字符串，支持：

| kind | 匹配对象 |
|---|---|
| `label` | 证据项的 label（大小写不敏感） |
| `title` | 证据项标题子串（大小写不敏感） |

- 过滤对**每个证据项**生效，不区分类别。因此 `label:` 正向过滤会把没有 label 的 commit / ci_run 一起排除，导致没有水位（`PARTIAL` + `watermark_not_in_scope`）；需要 label 过滤时请把 `evidence_scope` 收窄到 PR / issue。
- 排除命中计入报告 `excluded_count`；正向过滤未命中也计数（`inclusion_misses`），不静默丢弃。
- 未知 kind、缺值或超长（>200）视为配置错误，扫描拒绝开始（退出码 `1`），不猜语义。
- 不提供 `path:` / `branch:` 过滤：那需要额外读取 PR 文件列表，超出“最小证据范围”，本任务未实现。

## 8. 限制与未验证项（不得当作已通过）

- **首轮真实扫描已完成，但覆盖不完整（2026-10-26）。** 两个来源都返回 `PARTIAL`，没有 `OK` 水位：`talkdnd` 的 `issue` / `commit` / `ci_run` 与 `agentmgr` 的 `commit` / `ci_run` 达到分页上限，`agentmgr` 的 `issue` 类别在扫描时因一次瞬时 EOF 未读取（`unexpected_command_failure`）。`scan_cursor` 已记录 `PARTIAL`，但 `last_successful_scan_at` / `last_scanned_commit` 仍为 `null`。因此本次不能写“已完整扫描”或“无新经验”；详见 §10 与脱敏报告 [`live-scan-2026-10-26.md`](live-scan-2026-10-26.md)。来源可达性、速率限制与真实语义质量仍需后续扫描验证。
- `gh` CLI 的实际版本、认证状态与 CI 环境可用性未探测；适配器只保证“缺失时降级为 `BLOCKED:tool_unavailable`”。
- `review` 端点只读取 review comment 列表，不含 PR review 汇总；CI 只读 Actions run 列表，不读 job / step 日志。
- 分页默认最多 3 页 × 30 条，超出即 `PARTIAL`；不实现断点续采。
- 无法区分“仓库只有一页”与“恰好读到一页上限”之外的更细截断信息。
- 采集层不做语义判断：判定“根因 / 影响 / 是否通用”属于教训分析，见 [lessons-implementation.md](lessons-implementation.md)。
- 报告默认写入 `.local/self-improvement/`（git-ignored），不进入仓库、不随发行包发布。

## 9. 本机真实验证（#49 分支，Python 3.13.5）

```bash
python3 scripts/validate_kit.py                 # 退出码 0
python3 -m unittest discover -s tests           # 退出码 0
python3 -m unittest tests.self_improvement      # 退出码 0
python3 -m py_compile scripts/orchestrator.py scripts/validate_kit.py   # 退出码 0
python3 scripts/build_release.py                # 退出码 0（未改发行清单）
python3 scripts/self_improvement/cli.py registry validate   # 退出码 0
python3 scripts/self_improvement/cli.py registry show       # 退出码 0
```

上述命令在提交前的 head 上真实执行；具体输出与退出码见 PR 评论的证据矩阵。CI 结果以当前 head 的运行链接为准，未运行即 `NOT_RUN`。

## 10. 首轮真实扫描（#74，2026-10-26）

命令与退出码（在本任务 Worktree 中真实执行）：

```bash
python3 scripts/self_improvement/cli.py registry validate    # 退出码 0
python3 scripts/self_improvement/cli.py registry show --json # 退出码 0；扫描前两来源 enabled/public/cursor null
python3 scripts/self_improvement/cli.py scan --json          # 退出码 0；两来源均 PARTIAL
python3 scripts/self_improvement/cli.py lesson list          # 退出码 0；no lessons recorded
```

- 窗口：`talkdnd` `2026-07-28T14:06:20Z` → `2026-10-26T14:06:20Z`（90 天，`first_scan`）；`agentmgr` `2026-08-27T14:06:20Z` → `2026-10-26T14:06:20Z`（60 天，`first_scan`）。
- 结果：两个来源都是 `PARTIAL`，没有 `OK`，所以 `last_successful_scan_at` / `last_scanned_commit` 仍为 `null`，cursor 未推进。
  - `talkdnd`：316 条证据（PR 85 / issue 51 / commit 90 / ci_run 90 / review 0）；`issue`、`commit`、`ci_run` 达到分页上限（3 × 30）。
  - `agentmgr`：223 条证据（PR 43 / issue 0 / commit 90 / ci_run 90）；`issue` 类别在扫描时因一次瞬时 EOF 未读取（`unexpected_command_failure`），`commit`、`ci_run` 达到分页上限。
- 排除 / 可疑指令形态 / 无效链接 / 脱敏命中均为 0；没有下载 PR / Issue 正文、diff、review 正文、CI 日志或提示词。
- 报告：`.local/self-improvement/reports/scan-20261026T140620Z.{json,md}`（本地、git-ignored、不入库）；脱敏摘要见 [`live-scan-2026-10-26.md`](live-scan-2026-10-26.md)。
- 本次没有提供显式分析，lesson store 仍为 0 条；管线不会从标题推断根因（[lesson-lifecycle.md](lesson-lifecycle.md) §9）。结论是“本次无候选”，不是“来源无新经验”。
- 仍未验证：窗口前段因分页上限未读；`agentmgr` issue 元数据未进入本次报告；CI 结论在扫描后可能变化；`gh` 限速与认证状态只按本次命令结果记录。
- 测试已拆分（Master 决定，方案 1）：默认注册表测试允许 `null` 或 schema 合法游标（非 `OK` 可保留历史成功水位），`test_fresh_registry_does_not_claim_a_scan` 保留 fresh-registry 语义；真实 `PARTIAL` 游标保留。修复后 `python3 -m unittest discover -s tests` 退出码 `0`（674 个测试）。详见 [`live-scan-2026-10-26.md`](live-scan-2026-10-26.md) §10。
