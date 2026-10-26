# Architecture Contract 检查器（#48 实现记录）

> 契约语义权威：[`../architecture/architecture-contract.md`](../architecture/architecture-contract.md)；字段 / 枚举权威：[`../contracts/schemas/architecture-contract.schema.json`](../contracts/schemas/architecture-contract.schema.json)（均由 #47 冻结，本任务未修改）。
> 本文件只说明 #48 的**实现能力与边界**：检查器实际能证明什么、不能证明什么、如何接入 CI。契约本身与实现不一致时，以契约与 schema 为准并停下来登记缺陷。

## 1. 组件与入口

| 路径 | 职责 |
|---|---|
| [`scripts/architecture/check.py`](../../scripts/architecture/check.py) | CLI：定位契约、运行规则、输出文本或 JSON、决定退出码 |
| `scripts/architecture/contract.py` | 读取契约（`--contract` → `docs/PROJECT.md` 的 `architecture_contract_path` → 默认路径）并用标准库复刻 schema 校验 + 语义校验 |
| `scripts/architecture/adapters/python_ast.py` | Python `ast` 依赖边扫描；动态导入 / 无法解析构造报 `UNKNOWN` |
| `scripts/architecture/adapters/rust.py` | Rust 词法 `use` 扫描；工具链缺失时 `NOT_RUN` + 能力 `UNKNOWN` |
| `scripts/architecture/rules.py` | 四条硬规则、三条软指标、豁免降级、`UNKNOWN` / `NOT_RUN` 传播 |
| `scripts/architecture/report.py` | 报告结构与文本渲染；绑定 head SHA 与 `contract_version` |
| [`templates/architecture/`](../../templates/architecture/README.md) | 可复制契约模板与用法说明（随发行包发布） |
| [`tests/architecture/test_architecture_checker.py`](../../tests/architecture/test_architecture_checker.py) | 每条硬规则的正 / 负 fixture、契约非法场景、能力降级场景 |

全部实现仅用 Python 标准库；不联网、不写项目文件、不引入第三方运行依赖。

## 2. 契约定位与失败语义

1. `--contract <path>`（最优先，必须位于项目内）；
2. `docs/PROJECT.md` 可选键 `architecture_contract_path`；
3. 默认 `docs/architecture/contract.json`。

| 情况 | 行为 |
|---|---|
| 未声明且默认文件不存在 | `OFF` 等价：只读盘点 + `NOT_RUN`，退出码 0，不猜测模块 |
| 已声明但文件缺失 / 路径越界 / JSON 不可解析 | 配置错误，**失败关闭**，退出码 1（不退回 `OFF`） |
| schema / 语义非法 | `DIAGNOSTIC_ONLY` / `WARN` 下退出码 0 且报告 `contract_errors`；`ENFORCE` 或 `enforcement_mode` 本身不可读时退出码 1 |
| `schema_version` 不受支持 | 同上，失败关闭并提示升级，不猜读 |

## 3. 报告状态与阻断判定

| 状态 | 产生条件 | 退出码影响 |
|---|---|---|
| `ERROR` | 命中未豁免的 `ERROR` 级发现 | `ENFORCE` 下非零 |
| `WARNING` | 命中 `WARNING` 级发现，或 `ERROR` 被有效豁免（附 `waiver_id`） | 无 |
| `UNKNOWN` | 文件不可解析、动态导入、目标无法解析、规则未实现、参数不足、适配器能力不足 | 无，但显式计数 |
| `NOT_RUN` | 规则启用但未执行：`OFF`、适配器被禁用、Rust 工具链缺失 | 无，但不计为通过 |
| `PASS` | 实际执行且无发现 | 无 |

- 汇总 `status` 取最严重发现；`blocking` 单独由 `enforcement_mode` 与发现计算，因此 `DIAGNOSTIC_ONLY` 可以报告 `ERROR` 却不阻断。
- `counts` 分开统计 `ERROR` / `WARNING` / `UNKNOWN` / `NOT_RUN` / `PASS`（另附 `waived`）；`UNKNOWN` 与 `NOT_RUN` 永不折算为 `PASS`。
- 报告始终包含 `head_sha`（git HEAD、`--head-sha` 显式值，或 `null` + `head_sha_source: "unavailable"`）与 `contract_version`。

## 4. 硬规则与定位信息

| 规则 | 判定 | 定位字段 |
|---|---|---|
| `NO_CYCLE` | 模块图 Tarjan 强连通分量；路径按模块 id 排序稳定输出 | `rule_id`、`modules`、`file`、`line`、`message` |
| `FORBIDDEN_EDGE` | 命中 `dependencies.forbidden`（`from` / `to` 支持 `*`） | `rule_id`、`module_id`、`target_module`、`file`、`line` |
| `LAYER_DIRECTION` | `params.order` + `direction` 定义允许方向，反向边即违规 | 同上 |
| `PRIVATE_ACCESS` | 跨模块导入目标文件落在对方 `private_paths` 前缀内 | `rule_id`、`module_id`、`target_module`、`file`、`line` |

软指标 `MODULE_FAN_OUT` / `MODULE_SIZE` / `INTERFACE_GROWTH` 无论契约写的 `severity` 是什么都只报 `WARNING`，消息含 `static metric` 字样；这是冻结语义"不得仅凭阈值阻断"的实现方式。

## 5. 适配器能力（未实测即 `UNKNOWN`）

| 适配器 | 已实现 | 明确不覆盖 | 降级 |
|---|---|---|---|
| Python | 静态 `import` / `from … import`（含相对导入、函数内导入，后者标记 `conditional`） | `importlib.import_module` / `__import__` / `exec` 拼装、字符串路由、无法解析的目标 | 逐条 `UNKNOWN`；文件解析失败整文件 `UNKNOWN` |
| Rust | `rustc` + `cargo` 均存在时，按 `use crate::…` 词法扫描解析到项目内文件 | braced / glob / 宏生成 `use`；跨 crate 依赖 | 工具链缺失：规则 `NOT_RUN`、能力 `UNKNOWN`；复杂声明逐条 `UNKNOWN` |

`capabilities` 分别记录两种语言的 `status` / `files_scanned` / 工具链探测结果，**不汇总成单一"整体通过"**。`--disable-adapter python|rust` 用于显式降级与可复现测试。

## 6. 接入点

| 位置 | 接入方式 |
|---|---|
| [`scripts/validate_kit.py`](../../scripts/validate_kit.py) | 检查器与模板、测试进入 `REQUIRED`（同时是发行包清单），缺失即结构自检失败 |
| [`scripts/build_release.py`](../../scripts/build_release.py) | 自检 h：解压包内运行 `check.py`，在无契约的包上必须退出 0 且 `enforcement_mode=OFF`（证明导入与降级可用） |
| `.github/workflows/ci.yml` | 每个 PR / push 以 `--json` 在无契约的仓库上跑诊断模式；`py_compile` 覆盖新增脚本 |
| `docs/PROJECT.md` | 新增可选键 `architecture_contract_path`；不配置即 `OFF` |
| #50 / #53 | 读取 JSON 报告：`status`、`counts`、`findings[].rule_id`、`head_sha`、`capabilities` |

本仓库自身没有 Architecture Contract（`docs/architecture/` 只有冻结文档），所以 CI 上运行的是诊断模式回归，不代表任何项目已被 `ENFORCE`。

## 7. 已知限制与未验证范围

- Python 依赖边是**静态**结论：运行时注入、反射、插件加载不会被识别，只会以 `UNKNOWN` 提示。
- Rust 适配器没有用 `cargo metadata` 或 rustc 编译单元，模块归属依赖 `src/` 路径约定；不覆盖 workspace 多 crate 解析。
- `LAYER_DIRECTION` 的 `order` / `direction` 参数是本实现的参数形状（冻结设计只定义规则种类、未定义算法），修改形状需同步模板与测试。
- 软指标没有历史数据来源；`INTERFACE_GROWTH` 依赖契约里手写的 `baseline`，不是自动趋势。
- 未实测：Windows 路径与大小写不敏感文件系统上的行为；Rust 适配器在真实 workspace 上的准确性。这些能力在报告里不会被声明为已验证。
