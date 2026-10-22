# 从旧版升级到 1.3（2026-10）

> 本文件是**仓库文档**，不随发行包发布（`docs/` 不在打包清单内）。发行包使用者看 [README.md](../README.md) 第 10 节「从旧版升级（1.1 → 1.3）」，那一节已经包含四条路径的最小可复制步骤；本文是它的完整版：分步清单、报错原文、退出码含义与回退。
> 本文只写「旧文件长什么样、命令怎么改、自检看到什么」，**不重述契约**：
>
> - `edition` 的权威来源、合法值与失败关闭：[README.md](../README.md) 6.1 / 6.2
> - 计划分两层（设计目标 / 阶段计划）：[AGENTS.md](../AGENTS.md) 第 8 条
> - 资源锁语义（冲突矩阵、租约与恢复、底座边界）：[docs/design/RESOURCE-LOCKS.md](design/RESOURCE-LOCKS.md)
> - 清单格式、文件分类与漂移诊断口径：[docs/RELEASE-DRIFT.md](RELEASE-DRIFT.md)
>
> 本文出现的每条命令与每个退出码都在 2026-10-23 于 Windows 10 + Git Bash + Python 3.13 上**真实执行**过，逐条记录见第 9 节。未实测的部分会明写「未实测」。

## 1. 适用对象与四条迁移路径

适用于还在 `Format version` 1.1 / 1.2、要升到 1.3 的项目，`local` 与 `github` 两种底座都适用（底座差异写在每节的「底座差异」里）。

四条路径对应四种旧起点，**命中几条改几条**，彼此独立：

| # | 旧起点 | 现在会撞到什么 | 改哪里 |
| --- | --- | --- | --- |
| 1 | `ORCHESTRATION-PROJECT.md` 的 `edition` 是旧格式（多取值、带说明文字、重复声明、无列表符号） | 调度被阻断；`config show` 退出码 1 | `ORCHESTRATION-PROJECT.md` 一行 |
| 2 | 根 `PLAN.md` 是「设计目标 + 阶段 + 任务块 + 状态表」混装的台账 | 不报错，但计划分两层后方向与进度读不出唯一答案 | 根 `PLAN.md` + 新增 `docs/` 阶段计划 |
| 3 | 用了具名资源锁，但 `.orchestration/config.json` 没配 `resource_lease_ttl` | 派发失败：`RESOURCE_CONFIG_INVALID` | `.orchestration/config.json` |
| 4 | 旧包没有 `MANIFEST.json` | `check_drift.py` 报 `version-unknown`、退出码 2（不是崩溃） | 登记一份基线清单 |

**没有自动迁移。** 套件不提供迁移脚本，`init` 也不会替你拆分计划（见 4.4），四条都要手工做。迁移只改项目自己的文件，不改套件版本策略（`VERSION.txt` 由维护者更新，不是升级动作的一部分）。

## 2. 升级前准备

```bash
python scripts/orchestrator.py backup        # 备份 .orchestration/state.sqlite3
python scripts/orchestrator.py config show   # 记录升级前的生效值（edition 可能已报错）
git rev-parse HEAD                           # 记录升级前 head，回退时要用
```

`backup` 的实测行为：写入 `.orchestration/backups/state-<YYYYMMDD>-<HHMMSS>.sqlite3`，退出码 0。

```text
$ python scripts/orchestrator.py backup
Backup created: <项目根>\.orchestration\backups\state-20261023-011527.sqlite3
# exit 0
```

如果 `config show` 现在就已经退出码 1，先做第 3 节——`edition` 不合法时其余调度命令都不可用，其它三条也验不了。

## 3. 迁移一：`edition` 旧格式行

### 3.1 先判断自己是不是旧格式

```bash
grep -n "edition" ORCHESTRATION-PROJECT.md
```

以下四种形态都属于旧格式，都会被拒：

| 形态 | 例子 |
| --- | --- |
| A 取值带说明文字 | ``- `edition`: local（单人本地；需要多人协作时改为 github）`` |
| B 多取值 | ``- `edition`: local / github`` 或 ``local, github`` |
| C 重复声明 | 文件里出现两行 `edition` |
| D 不是列表项 | `edition: local`（没有列表符号），或写在两列表格里（字段名一列、取值一列） |

### 3.2 为什么被拒

1.3 起 `edition` 只在 `ORCHESTRATION-PROJECT.md` 里读，且**只认裸取值** `local` / `github`：取值带说明文字或多写几个取值时，路由无法唯一确定底座，所以现在**失败关闭**——报出实际值与文件位置，不再回落到 `local`。`.orchestration/config.json` 里的 `edition` 键不再生效，只作为历史记录显示（`config show` 会标注 `legacy key is ignored`）。

### 3.3 真实报错（四条，形态与退出码都不同）

形态 A（带说明文字）：

```text
$ python scripts/orchestrator.py config show
ERROR: ORCHESTRATION-PROJECT.md: key `edition` has unsupported value 'local（单人本地；需要多人协作时改为 github）' in <项目根>\ORCHESTRATION-PROJECT.md; allowed values are local, github (write the value alone, with no extra text)
# exit 1
```

形态 B（多取值）：

```text
ERROR: ORCHESTRATION-PROJECT.md: key `edition` has unsupported value 'local / github' in <项目根>\ORCHESTRATION-PROJECT.md; allowed values are local, github (write the value alone, with no extra text)
# exit 1
```

形态 C（重复声明，会指到行号）：

```text
ERROR: ORCHESTRATION-PROJECT.md: key `edition` is declared 2 times (lines 2, 4) in <项目根>\ORCHESTRATION-PROJECT.md; keep exactly one declaration
# exit 1
```

形态 D（没有列表符号或写在表格里，报的是"缺键"而不是"值非法"）：

```text
ERROR: ORCHESTRATION-PROJECT.md: missing required key `edition` in <项目根>\ORCHESTRATION-PROJECT.md; add one line "- `edition`: local" or "- `edition`: github"
# exit 1
```

补充：`config show` 仍会把 `retry_cap` / `local_dir` 表格打到 stdout，`ERROR` 行打到 stderr，`edition` 显示为 `(invalid)`。所以只看 stdout 会以为"没有报错"，**必须看退出码或 stderr**。

### 3.4 改法

```diff
- `edition`: local（单人本地；需要多人协作时改为 github）
+ `edition`: local
```

规则只有四条：**一行**、**以 `-` 或 `*` 开头**、**冒号后只写取值**、**不加引号 / 括号 / 斜杠 / 大小写变体**（`LOCAL`、`Local` 都不合法）。

- 同时把 `.orchestration/config.json` 里残留的 `edition` 删掉（不删也不影响，但会多一行 `legacy key is ignored`）。
- `github` 底座写 ``- `edition`: github``；底座切换是单向、一次性动作，切换规则见 [AGENT-ORCHESTRATION.md](../AGENT-ORCHESTRATION.md) 第 6 节，**不要**为了升级把 `local` 项目写成 `github`。

### 3.5 自检

```bash
python scripts/orchestrator.py config show
```

```text
Config file: <项目根>\.orchestration\config.json
  retry_cap  = 3          (source: config.json)
  local_dir  = .local     (source: config.json)
  edition    = local      (source: ORCHESTRATION-PROJECT.md)
Edition is selected only by `edition` in <项目根>\ORCHESTRATION-PROJECT.md; config.json holds local CLI runtime parameters (retry_cap, local_dir) and never selects an edition.
Edit .orchestration/config.json to change retry_cap or local_dir; invalid values there fall back to defaults.
# exit 0
```

判据：`edition` 一行**不是** `(invalid)`，`source` 为 `ORCHESTRATION-PROJECT.md`，退出码 0。`github` 底座下还会多一行说明（调度命令被拒绝，矩阵见 [README.md](../README.md) 6.2），退出码同样是 0。

### 3.6 不要这样做

- 不要写 ``- `edition`: local, github`` 期望"两个底座都支持"——多取值一律拒绝。
- 不要靠 `.orchestration/config.json` 里的 `edition` 生效，它已经不是权威来源。
- 不要在报错后继续跑 `task dispatch` 看看"能不能凑合过"，它只会复述同一个 `EditionError`。

## 4. 迁移二：根 `PLAN.md` 台账 → 设计目标 + `docs/` 阶段计划

### 4.1 判断自己是不是旧台账

```bash
grep -n '^|' PLAN.md
```

命中「任务 / 阶段 / 状态」这类表格行，或文件里还带着任务块字段（`Allowed paths`、`AC-1`、`Depends on`），就是旧台账格式。

```text
3:| 任务 | 阶段 | 状态 |
4:|---|---|---|
5:| TASK-0001 | Phase A | 已完成 |
# exit 0
```

### 4.2 目标形态

计划分两层，权威口径在 [AGENTS.md](../AGENTS.md) 第 8 条，这里只引用不复述：根 `PLAN.md` 只承载设计目标；阶段目标、任务顺序、依赖、任务块与状态搬到 `docs/` 的阶段计划。

1.3 之前只有根 `PLAN.md` 一个计划文件，所以旧项目把两层内容混在一起。升级后：

| 文件 | 只写这些 | 模板 |
| --- | --- | --- |
| 根 `PLAN.md` | 问题与目标用户、设计目标、设计原则、范围与非目标、全局约束、可度量的全局验收 | [templates/PLAN.md](../templates/PLAN.md) |
| `docs/` 阶段计划 | 计划头部、当前状态表、阶段（目标 / 交付 / 出口）、任务块、维护规则 | [templates/IMPLEMENTATION-PLAN.md](../templates/IMPLEMENTATION-PLAN.md) |

### 4.3 拆分步骤（手工，四步）

1. 复制阶段计划模板：

   ```bash
   mkdir -p docs
   cp templates/IMPLEMENTATION-PLAN.md docs/IMPLEMENTATION-PLAN.md
   ```

2. 把旧台账里的**阶段目标、任务顺序与依赖、任务块、状态表**搬到 `docs/IMPLEMENTATION-PLAN.md`。状态表从此是唯一落点；已关闭 / 取消的任务保留行并注明结果。

3. 把根 `PLAN.md` 收敛为设计目标：删掉阶段划分、任务清单与状态表，只留 4.2 表里左列六类内容。`templates/PLAN.md` 的同名章节可以直接对照（`## 问题与目标用户` / `## 设计目标` / `## 设计原则` / `## 范围与非目标` / `## 全局约束` / `## 可度量的全局验收`）。

4. 在根 `PLAN.md` 顶部补一句指向阶段计划的说明（模板里的 `## 计划文件` 一节就是这个用途），避免下一个会话只读到设计目标就以为"没有计划"。

同时删掉项目里可能存在的第二份"计划"备份（例如 `PLAN-old.md`、`docs/PLAN.md` 双写），否则又变成两处状态。

### 4.4 `init` 的确定行为（实测）

`init` 发现根 `PLAN.md` 已存在时**原样保留**，不拆分、不合并、不覆盖：

```text
$ python scripts/orchestrator.py init
...
PLAN.md already present, kept unchanged: <项目根>\PLAN.md
Next: judge task direction from the design goals in the root PLAN.md; templates/PLAN.md is only the initial copy.
# exit 0
```

实测同一旧台账文件在 `init` 前后内容与表格行数不变（3 行表格 → 3 行表格）。所以**不要指望跑一条命令就把台账拆开**；反过来，升级时也不必担心 `init` 弄坏你的计划文件。

### 4.5 自检

```bash
grep -n '^|' PLAN.md || echo "no table rows: PLAN.md carries no task status table"
```

```text
no table rows: PLAN.md carries no task status table
# exit 0
```

再跑套件自带的两条检查（在套件安装目录，即项目根执行）：

```bash
python scripts/validate_kit.py
python -m unittest discover -s tests
```

两条都应以退出码 0 结束（`validate_kit.py` 打印 `Kit validation passed ...`，`unittest` 打印 `OK`）。人工再确认一遍：`docs/IMPLEMENTATION-PLAN.md` 的「当前状态」表与任务载体（`local` 任务库 / `github` Issue）描述的是同一批任务，没有一边写着 `已完成`、另一边还在 `DISPATCHED`。

### 4.6 不要这样做

- 不要保留"根 `PLAN.md` 写状态、`docs/` 也写状态"的双写：两边冲突时按设计目标停下对齐，代价比现在就拆开高得多。
- 不要把阶段计划放在根目录另起一个名字（`PLAN-2.md`）——按归属它是 `docs/` 下的文件，放在根目录会被当成第二份设计目标。
- 不要直接改 `templates/PLAN.md` / `templates/IMPLEMENTATION-PLAN.md` 来"适配"自己的项目：模板要保持项目无关，改模板会让下一次升级更难。

## 5. 迁移三：资源锁必须显式配 `resource_lease_ttl`

### 5.1 什么时候会撞上

任务用 `--resources` 声明了具名资源（例如 `db:test/mysql-main:exclusive`），并且声明字符串里**没有**带 `:<ttl>`，`task dispatch` 就会去 `.orchestration/config.json` 读 `resource_lease_ttl`。这个键**没有内置默认值**，没配就拒绝派发。

### 5.2 真实报错

```text
$ python scripts/orchestrator.py task dispatch TASK-0001 --holder "runner:local-01" --evidence "smoke"
ERROR: RESOURCE_CONFIG_INVALID: resource lock configuration is missing or illegal: resource_lease_ttl must be an integer between 1 and 604800 in <项目根>\.orchestration\config.json; add it to .orchestration/config.json (a lease without an explicit ttl or cool-down is refused)
# exit 1
```

同一族报错还有两处，容易被忽略：

```text
# task renew：总是读 config 的 resource_lease_ttl
ERROR: RESOURCE_CONFIG_INVALID: resource lock configuration is missing or illegal: resource_lease_ttl must be an integer between 1 and 604800 in <项目根>\.orchestration\config.json; ...

# task reclaim：总是读 config 的 resource_reclaim_grace
ERROR: RESOURCE_CONFIG_INVALID: resource lock configuration is missing or illegal: resource_reclaim_grace must be an integer between 0 and 86400 in <项目根>\.orchestration\config.json; ...
```

三者都以退出码 1 结束，而且都发生在**写锁之前**：缺 ttl 时派发不会留下半套锁，`task renew` 也不会改动已有租约（实测失败前后 `lease_until` 不变）。

### 5.3 改法

`.orchestration/config.json`（`resource_lease_ttl` 必填才有资源锁能力；`resource_reclaim_grace` 只有 `task reclaim` 需要，建议一起配）：

```json
{
  "retry_cap": 3,
  "local_dir": ".local",
  "resource_lease_ttl": 900,
  "resource_reclaim_grace": 300
}
```

- `resource_lease_ttl`：整数 1–604800（秒）。示例 900 = 15 分钟租约。
- `resource_reclaim_grace`：整数 0–86400（秒）。示例 300 = 过期后 5 分钟冷却，冷却期内 `task reclaim` 一律拒绝。
- 必须是**JSON 整数**：`"900"`（字符串）、`900.0`（浮点）、负数都不合法，会得到同一条 `RESOURCE_CONFIG_INVALID`；ttl 还要求 ≥ 1，而 grace 允许 `0`。
- **未声明资源的任务完全不读这两个键**，所以升级后不配它们也不影响原有任务。

### 5.4 自检

```bash
python scripts/orchestrator.py task dispatch TASK-0001 --holder "runner:local-01" --evidence "smoke"
```

```text
TASK-0001: DISPATCHED; locks acquired for tests
TASK-0001: resource locks GRANTED for db:test/mysql-main:exclusive (holder runner:local-01, fingerprint 799038d52a7d)
Now pass the self-contained task packet to a real Execution Agent. This command does not launch agents.
# exit 0
```

```bash
python scripts/orchestrator.py task resources
```

```text
resource_id	mode	state	lease	holder	task	backend	lock_id	blocking
db:test/mysql-main	exclusive	ACTIVE	lease_until=...	renewed_at=...	holder=runner:local-01	task=TASK-0001	backend=local	lock_id=db:test/mysql-main#exclusive#TASK-0001#0	blocks=exclusive+shared
Total: 1 row(s); generated with the frozen contract docs/design/RESOURCE-LOCKS.md.
# exit 0
```

判据：`state=ACTIVE` 且 `lease_until` 与配置的 ttl 相符（示例 900 秒 = 15 分钟）。

### 5.5 底座差异与边界

- **`github` 底座不需要配**这两个键：本地 CLI 在 `github` 下拒绝 `task dispatch` / `renew` / `reclaim`（报 `edition is 'github' ...`，退出码 1），资源占用只以 Issue 登记块协作记录，不走这套租约。
- 声明里自带 ttl（`db:test/mysql-main:exclusive:600`）时，`task dispatch` 不读 config 的 `resource_lease_ttl`；但 `task renew` 仍然读它（实测：config 里没有该键时 `renew` 报 `RESOURCE_CONFIG_INVALID`）。
- 租约到期只是转 `EXPIRED`，**不释放、也不等于空闲**；语义见 [docs/design/RESOURCE-LOCKS.md](design/RESOURCE-LOCKS.md)。

### 5.6 不要这样做

- 不要把这两个键写进 `ORCHESTRATION-PROJECT.md`（那里只管项目底座与门禁口径），也不要在 `config.json` 里写注释（JSON 不接受注释，损坏后 `retry_cap` / `local_dir` 会静默回落默认值）。
- 不要因为"反正没有默认值"就把 ttl 设成 604800 求稳：租约越长，崩掉的任务占着资源的时间越长。
- 不要用 `task unlock --force` 绕过配置错误：`RESOURCE_CONFIG_INVALID` 是配置问题，解锁不会让下一次派发通过。

## 6. 迁移四：旧包没有 `MANIFEST.json`

### 6.1 现象

```bash
python scripts/check_drift.py .
```

```text
status: version-unknown (exit 2)
manifest: absent (no MANIFEST.json)
checked: 0 manifest file(s); missing 0, modified 0, unknown 0, project-profile 0, extensions 0
note: no MANIFEST.json in this project: suite version unknown, no baselines to compare
note: register a baseline: keep the manifest from the kit release you started from (or rebuild one with scripts/build_release.py), the tool never guesses a version
note: this is a diagnosis only; reading and using the project is not blocked
# exit 2
```

**退出码 2 不是崩溃**，意思是"版本未知 / 需要登记基线"。工具不会按文件内容或 `VERSION.txt` 猜一个版本，也不会因为这个报告阻止你继续用项目。

### 6.2 退出码含义

| 退出码 | 含义 | 该做什么 |
| --- | --- | --- |
| `0` | clean：核心文件齐全且未被改；`project-profile`（`ORCHESTRATION-PROJECT.md` / `PLAN.md` / `DESIGN.md`）差异与本地扩展只列出、不算 drift | 不需要动作 |
| `2` | drift：核心文件缺失或被改、上游目录里有清单不认识的 `unknown` 文件、清单 schema 超出工具支持范围，**或项目没有 `MANIFEST.json`（version-unknown）** | 有人看一眼报告，判断是否本意 |
| `1` | 输入无效或工具错误：项目根不存在 / 不是目录、`MANIFEST.json` 不是合法 JSON 或结构不合法 | 先修输入，这一次诊断没有完成 |

完整口径（分类规则、只读保证）见 [docs/RELEASE-DRIFT.md](RELEASE-DRIFT.md)；面向使用者的摘要见 [README.md](../README.md) 8.2。

### 6.3 登记基线（两条来源）

**来源 A：当初那份发行包。** 把安装时那个 zip 里的 `MANIFEST.json` 放到项目根即可——它记录的正是你这棵树的上游基线。

```bash
python -m zipfile -e agentorch-<日期>.zip <解压目录>
cp <解压目录>/agentorch-<日期>/MANIFEST.json .
```

**来源 B：在该版本的套件仓库里重建。** 找不到原包时，用与安装版本一致的仓库 checkout 重新构建一次，再从产物里取清单：

```bash
python scripts/build_release.py --date 20261023 --output-dir /tmp/baseline
python -m zipfile -e /tmp/baseline/agentorch-20261023.zip /tmp/baseline-extract
cp /tmp/baseline-extract/agentorch-20261023/MANIFEST.json .
```

实测：

```text
$ python scripts/build_release.py --date 20261023 --output-dir /tmp/baseline
Release self-check passed (checks a-f).
  package files : 48 (47 REQUIRED + MANIFEST.json)
  manifest      : schema 1, suite 'Agent-Orchestration Starter Kit', format 1.3
  zip path      : /tmp/baseline/agentorch-20261023.zip
# exit 0
```

注意两点事实：

- **`scripts/build_release.py` 不随发行包发布**：包内 `scripts/` 只有 `check_drift.py`、`orchestrator.py`、`report_metrics.py`、`validate_kit.py`。所以来源 B 只能在仓库 checkout 上做；只有发行包的用户请用来源 A。
- 来源 B 重建的是**那棵树当前的上游文件**。如果这棵树早就被改过，重建出来的基线会把这些改动当成"本来就该这样"，历史漂移就查不出来了。基线要么来自原包，要么来自干净的同版本 checkout。

### 6.4 只读、不覆盖

- `check_drift.py` 本身**只读**：只 `read_bytes` / `read_text` / `os.walk`，没有 `--fix` / `--sync`，也不跟随符号链接。它不会创建、重命名、删除或覆盖项目里的任何文件。
- 第 6.3 节的 `cp` 是**你手动做的登记动作**，不是工具替你改树。想撤销就删掉 `MANIFEST.json`，回到 `version-unknown`。
- 不要把**新版**清单套到**旧**树上：那会把每一个上游文件都报成 `modified`，看起来像"整个套件被改过"。
- 不要为了"让报告变绿"去改核心文件或删本地扩展：报告只描述事实，改文件才改变事实。

### 6.5 自检

登记基线后：

```bash
python scripts/check_drift.py .
```

```text
status: clean (exit 0)
manifest: schema 1 (supported: yes), suite 'Agent-Orchestration Starter Kit', format 1.3
checked: 47 manifest file(s); missing 0, modified 0, unknown 0, project-profile 2, extensions 0
  [project-profile] ORCHESTRATION-PROJECT.md - project-profile
  [project-profile] PLAN.md - added locally
note: 2 project-profile file(s) differ from the shipped template, which is expected after a project fills them in
# exit 0
```

`project-profile` 条目**正常**：`ORCHESTRATION-PROJECT.md` 与 `PLAN.md` 本来就该被项目填写。

再确认基线真的能检出改动（改一个核心文件再还原）：

```text
status: drift (exit 2)
checked: 47 manifest file(s); missing 0, modified 1, unknown 0, project-profile 2, extensions 0
  [modified] AGENTS.md - core
# exit 2
```

### 6.6 不要这样做

- 不要期望工具"猜一个版本"后自己对齐：没有清单就没有可信基线，这是设计选择，不是缺口。
- 不要把 `unknown`（落在 `editions/`、`templates/`、`scripts/`、`prompts/`、`tests/` 里、清单不认识的文件）当成本地扩展忽略掉：它可能是旧版本残留，值得人工确认。
- 不要在升级过程中顺手"同步"上游文件：套件不做覆盖，需求是差异可解释，不是文件一致。

## 7. 一次跑完的清单

按顺序执行，每步的退出码即判据：

| # | 步骤 | 命令 | 期望退出码 |
| --- | --- | --- | --- |
| 1 | 备份任务库 | `python scripts/orchestrator.py backup` | `0` |
| 2 | 修 `edition` 旧格式 | 编辑 `ORCHESTRATION-PROJECT.md`，只留 ``- `edition`: local`` | — |
| 3 | 验证底座 | `python scripts/orchestrator.py config show` | `0`（`edition` 不是 `(invalid)`） |
| 4 | 拆分计划 | `cp templates/IMPLEMENTATION-PLAN.md docs/IMPLEMENTATION-PLAN.md`，把阶段与状态搬过去 | — |
| 5 | 验证根计划无状态表 | `grep -n '^|' PLAN.md` | 无输出（提示行由 `||` 分支打印） |
| 6 | 配资源锁 | 在 `.orchestration/config.json` 加 `resource_lease_ttl`（+ 可选 `resource_reclaim_grace`） | — |
| 7 | 验证派发 | `python scripts/orchestrator.py task dispatch <ID> --holder <可定位ID> --evidence <证据引用>` | `0` |
| 8 | 登记基线 | 见 6.3，把 `MANIFEST.json` 放到项目根 | — |
| 9 | 验证漂移诊断 | `python scripts/check_drift.py .` | `0`（登记基线之前会得到 `2`） |
| 10 | 套件自检 | `python scripts/validate_kit.py` 与 `python -m unittest discover -s tests` | 都是 `0` |

第 7 步只对 `local` 底座有意义；`github` 底座的派发由 Issue / PR 承载，本地 CLI 会明确拒绝。

## 8. 回退

四条迁移都是"文档 + 一个 JSON 键 + 一个基线文件"，逐条可回退，互不牵连。

| 迁移 | 回退动作 | 回退后状态 |
| --- | --- | --- |
| `edition` | `git checkout -- ORCHESTRATION-PROJECT.md` | 回到旧格式 = 重新阻断调度。**除非要放弃升级，否则不要回退这一条** |
| 计划分层 | `git checkout -- PLAN.md`，并删除新拆出的 `docs/IMPLEMENTATION-PLAN.md` | 回到单文件台账；任务载体里的状态不受影响（状态本来就不在 `PLAN.md` 里权威） |
| 资源锁 | 从 `.orchestration/config.json` 删除 `resource_lease_ttl` / `resource_reclaim_grace` | 未声明资源的任务照常派发；声明了资源的任务重新报 `RESOURCE_CONFIG_INVALID`。已写入的租约**仍在锁表里**（实测删键后 `task resources` 仍列出 `ACTIVE`），只是 `task renew` 会因缺 ttl 失败——要么补回配置，要么等它过期后按锁语义处置 |
| 基线清单 | `rm MANIFEST.json` | 回到 `version-unknown`、退出码 2；诊断不阻断使用 |

任务库层面的回退（以下**未实测**，属人工操作，动手前先停止派发）：`python scripts/orchestrator.py backup` 生成的 `.orchestration/backups/state-<时间戳>.sqlite3`，在确认没有其它会话在用任务库后，用它替换 `.orchestration/state.sqlite3` 即可回到备份时刻。

**回退的硬边界**：任何回退都不得造成双写——同一个任务不能同时在 `local` 任务库和 GitHub Issue 里维护状态。底座切换与回退规则见 [AGENT-ORCHESTRATION.md](../AGENT-ORCHESTRATION.md) 第 6 节。

## 9. 本轮实测记录

环境：Windows 10（MINGW64 / Git Bash）、Python 3.13、套件 `Format version` 1.3、`main` = `25d1573`。
实验都在系统临时目录里构造旧格式文件完成，**没有改动本仓库自己的 `.orchestration/` 配置**。

| # | 场景 | 命令 | 实测退出码 |
| --- | --- | --- | --- |
| 1 | `edition` 带说明文字 | `orchestrator.py --root <tmp> config show` | `1`（`unsupported value 'local（单人本地…）'`） |
| 2 | `edition` 多取值 `local / github` | 同上 | `1`（`unsupported value 'local / github'`） |
| 3 | `edition` 重复声明两行 | 同上 | `1`（`declared 2 times (lines 2, 4)`） |
| 4 | `edition` 写成 `edition: local`（无列表符号） | 同上 | `1`（`missing required key`） |
| 5 | `edition` 写在表格行里 | 同上 | `1`（`missing required key`） |
| 6 | 修成裸取值 ``- `edition`: local`` | `config show` | `0` |
| 7 | 旧台账 `PLAN.md` + 已有 `templates/PLAN.md` | `orchestrator.py init` | `0`，打印 `PLAN.md already present, kept unchanged`；文件表格行数仍为 3 |
| 8 | 声明资源但缺 `resource_lease_ttl` | `task dispatch TASK-0001 --holder runner:local-01 --evidence smoke` | `1`（`RESOURCE_CONFIG_INVALID`） |
| 9 | 补齐 ttl=900 + grace=300 后重派 | 同上 | `0`（`locks GRANTED`） |
| 10 | 有 ttl、缺 grace | `task reclaim ...` | `1`（`resource_reclaim_grace must be an integer between 0 and 86400`） |
| 11 | 只剩 grace、缺 ttl | `task renew` / `task resources` | renew `1`（缺 ttl）；resources `0`（原锁仍 `ACTIVE`） |
| 12 | 旧项目无 `MANIFEST.json` | `check_drift.py <项目根>` | `2`（`version-unknown`） |
| 13 | 重建基线包 | `build_release.py --date 20261023 --output-dir /tmp/baseline` | `0`（48 个包内文件，manifest schema 1 / format 1.3） |
| 14 | 解压后的干净包 | `check_drift.py <解压目录>` | `0`（`clean`） |
| 15 | 旧项目放回基线清单 | `check_drift.py .` | `0`（`project-profile 2`，不算 drift） |
| 16 | 篡改 `AGENTS.md` 后再诊断 | `check_drift.py .` | `2`（`[modified] AGENTS.md - core`） |
| 17 | `github` 底座 | `config show` / `task dispatch` | `0`（附拒绝说明）/ `1`（`edition is 'github'`） |
| 18 | README 用 Markdown 链接指向 `docs/UPGRADE-2026-10.md` | 在包内跑 `validate_kit.py` | `1`（`broken relative link`，且清单哈希不匹配）——**所以 README 只写路径、不做链接** |
| 19 | ttl 写成 `"900"` / `0` / `900.0` / `-1` | `task dispatch` | 四种都是 `1`（`RESOURCE_CONFIG_INVALID`） |

## 10. 本文不做什么

- 不提供自动迁移脚本，也不改 `init` 的行为：四条迁移都是手工的，可审查、可回退。
- 不猜版本、不覆盖项目文件、不"同步"上游：漂移只报告差异。
- 不重述契约：`edition` 权威、计划分层、资源锁语义、清单分类各自由第 1 节列的文档定义，本文只引用。
- 不改版本策略：`Format version` 由维护者按发布规则更新，升级说明不改变发布与兼容承诺。
