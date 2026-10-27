# .local/ — 本机私有文件目录

本目录只存放**属于这台机器**的文件，用于把私有信息与可分享的仓库内容分开。本 README 本身是唯一会被 Git 跟踪的文件，因此这里不能写任何个人信息、凭据或主机事实。

## 用途

- `.env` 等环境变量与凭据；
- 机器 / 主机信息（CPU、内存、磁盘、解释器路径等本地事实）；
- 发布扫描规则（发给发布构建的额外禁用词）；
- AgentOrch 的本机角色发现、Subagent 能力考核、模型评测快照、选型历史和项目内反馈（仅放在 `.local/agent-orch/<scope-id>/`，每个终端独立）。

## 规则

- `.local/` 下除本 README 外的全部内容都被 Git 忽略（见 `.gitignore` 的 `.local/*` 与 `!.local/README.md`）。
- 永不提交、永不打包进发布产物。
- 需要跨机器共享的内容不放这里；本目录只服务于当前克隆。
- AgentOrch 的选型与能力记录必须使用 Markdown；不同终端 / Agent 会话使用不同的 `<scope-id>`，不得读写其他 scope 的记录。不能可靠识别当前 scope 时，不得回退到共享默认目录。
- 这些记录不上传、不同步、不提交、不进入发行包；只记录必要的摘要和证据引用，禁止写入凭据、完整私有提示词、原始对话或不必要的绝对路径。

## 建议布局（示例，不要提交真实文件）

```text
.local/
  README.md          # 本文件（唯一被跟踪）
  .env               # 环境变量与凭据
  local_info.md      # 机器事实：CPU / 内存 / 磁盘 / 实测可承载并发
  release-scan.json  # 发布构建使用的额外禁用词
  agent-orch/
    <scope-id>/
      README.md
      agent-registry.md
      runtime-capabilities.md
      model-evaluation-snapshots.md
      selection-history.md
      observed-performance.md
```

## 与模板的关系

新项目复制 `templates/gitignore.snippet` 后会得到同样的 `.local/*` + `!.local/README.md` 规则，因此同样受保护；不需要再手工添加。
