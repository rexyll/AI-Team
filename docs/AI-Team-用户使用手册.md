# AI-Team 用户使用手册

## 1. AI-Team 能做什么

AI-Team 接收一句软件需求，并尝试自动完成：

`需求理解 → 任务拆解 → 架构设计 → 编码 → 测试证据审查 → 代码审核 → 返工 → 项目结果`

你不需要直接调用五个 Agent；CLI 会自动建立团队并执行项目。

## 2. 第一次使用

进入仓库根目录：

```powershell
.\.venv\Scripts\Activate.ps1
python main.py "开发一个摄氏度转华氏度的 Python 命令行工具，所有文件放在 workspace/demo01/ 目录下，完成后运行验证"
```

运行后会看到类似：

```text
AI TEAM START
TASK-001 | architect | ...
TASK-002 | developer | ...
[Tool] write_file
[Tool] run_command
[Gate] ... tester=passed
[Gate] ... reviewer=approved
PROJECT RESULT
success=True status=completed completed=.../... 
FINAL TASK STATUS
```

## 3. 如何写好需求

推荐包含五类信息：

1. 做什么：功能目标。
2. 输入输出：数据、CLI 参数、API 等。
3. 技术约束：语言、框架、运行方式。
4. 文件约束：明确输出目录。
5. 验收方式：必须运行什么命令验证。

推荐：

```text
开发一个 Python 命令行工具，实现 CSV 文件统计。
要求：
1. Python 3.14；
2. 所有文件放在 workspace/csvstats/；
3. 提供 main.py；
4. 支持 --input 参数；
5. 至少包含单元测试；
6. 完成后运行测试并实际执行一次示例命令验证。
```

不推荐：

```text
做一个 CSV 工具，尽量完善。
```

需求越明确，Planner 越容易生成稳定的任务图。

## 4. Agent 各自做什么

### Planner

把自然语言需求拆成任务，并指定角色与 dependencies。它不写代码。

### Architect

负责结构、接口、数据模型、技术决策和风险分析，不修改文件。

### Developer

负责实际编码。它可以：

- 浏览文件
- 读取文件
- 创建/修改文件
- 移动/删除文件
- 运行测试/构建命令
- 执行 Git 工具

所有这些操作受工具 Schema 和 workspace sandbox 约束。

### Tester

不修改代码、不执行修改操作。它检查 Developer 是否提供可信测试证据，并输出：

`TEST_PASSED` 或 `TEST_FAILED`

### Reviewer

进行最终质量审核，并输出：

`APPROVED` 或 `REVISION_REQUIRED`

如果要求返工，Developer 会读取 Reviewer feedback 再次实现。

## 5. 工作区在哪里

默认工作区位于仓库之外的 `projects/`。

例如需求：

```text
所有文件放在 workspace/demo01/
```

产物会被约束到类似：

```text
AI-Team/
../projects/
└── workspace/
    └── demo01/
        ├── main.py
        └── ...
```

这样生成的业务代码不会默认进入 AI-Team 源码仓库。

## 6. 查看最终结果

CLI 会打印：

- 项目是否成功
- completed/total
- 每个任务的 ID
- 状态
- role
- title
- error（如有）

如果需要人工验收，建议进入对应项目目录查看真实文件，并亲自运行入口程序。

## 7. 理解任务状态

常见状态：

| 状态 | 含义 |
|---|---|
| pending | 等待依赖完成 |
| ready | 可以执行 |
| running | Agent 正在处理 |
| review_pending | Developer 已完成，等待质量门禁 |
| reviewing | 正在审核 |
| revision | 需要返工 |
| completed | 已完成 |
| failed | 执行失败 |
| blocked | 被失败/阻塞依赖挡住 |

## 8. Tester FAILED 怎么办

首先不要把 `TEST_FAILED` 当作系统故障。它是质量门禁结果。

检查：

1. Developer 修改了哪些文件。
2. Developer 实际执行了什么命令。
3. `tests` 中有没有真实测试结果。
4. Tester 指出的失败是否与需求相关。

如果确实失败，Workflow 会重新让 Developer 工作；如果超过最大审核轮次，任务会失败。

## 9. Reviewer REVISION_REQUIRED 怎么办

这是正常返工流程：

```text
Developer
   ↓
Tester
   ↓
Reviewer
   ↓
REVISION_REQUIRED
   ↓
Developer + Reviewer Feedback
   ↓
Tester
   ↓
Reviewer
```

默认最多 3 轮 Review Workflow。

## 10. 如何降低成本和运行时间

建议：

- 从单任务小项目开始。
- Planner/Tester 可以使用成本较低模型。
- Architect/Reviewer 使用能力更强的模型。
- Developer 任务尽量明确，减少无目标探索。
- 避免一次需求同时要求前后端、部署、数据库、UI 等大量内容。
- 利用 Developer pool 时，确保不同模型的职责和能力匹配。

## 11. 多模型配置

角色可以绑定不同 Provider/Model。例如：

```ini
PLANNER_MODEL=cheap-model
ARCHITECT_MODEL=strong-model
DEVELOPER_MODEL=coding-model
TESTER_MODEL=cheap-model
REVIEWER_MODEL=strong-model
```

Developer 还可以使用多个实例：

```ini
DEVELOPER_COUNT=2
DEVELOPER_1_MODEL=coding-model-a
DEVELOPER_2_MODEL=coding-model-b
```

相同 Task ID 在同一 pool 配置下会被确定性地映射到某一个 Developer。

## 12. 工具安全规则

Developer 不应该：

- 访问 sandbox 之外的文件
- 用文件系统 API 绕过 ToolRegistry
- 用 `run_command` 代替所有文件操作
- 修改系统目录
- 读取用户目录、注册表等非项目资源

正确方式：

- 浏览：`list_files`
- 读取：`read_file`
- 修改：`write_file`
- 移动：`move_file`
- 删除：`delete_file`
- 测试/构建：`run_command`
- Git：`git_command`

## 13. 如何保存运行日志

PowerShell：

```powershell
python main.py "..." *>&1 | Tee-Object -FilePath runs\run-001.log
```

运行日志对于分析模型质量、工具调用和返工原因非常有价值。

## 14. 常见错误

### 没有配置 Provider

检查 `.env`、`DEFAULT_PROVIDER`、`<PROVIDER>_API_KEY`、`<PROVIDER>_BASE_URL`。

### Planner 输出非法 JSON

缩小需求、明确验收条件，或者更换更稳定的模型。

### Developer 没有修改任何文件

系统会将“无 tool call、无文件修改、无命令执行”的情况视为无产物完成并失败。

### Developer 超过工具循环

默认最多 50 次工具循环。说明任务可能太复杂或模型陷入探索/修复循环。

### Tester 无法判定

Tester 必须输出 `TEST_PASSED` / `TEST_FAILED`。如果模型没有给出合法标记，Workflow 会按配置进行额外重试。

## 15. 当前重要边界

1. CLI 默认是即时内存运行，不会自动保存项目快照。
2. 项目持久化和事件持久化已经存在，但需要通过 Python Runtime API 显式接入。
3. Tester 主要依赖 Developer 提供的测试证据，并不会把“Developer 声称通过”当成真实执行证据。
4. Reviewer 也不会把主观报告直接视为事实。
5. LLM 本身不是可信执行环境；真正的文件访问边界由 ToolGuard 和 WorkspaceSandbox 强制实现。

## 16. 最佳实践

- 需求写清楚输出目录。
- 明确技术栈和验收命令。
- 第一轮先做小项目验证 Provider 和模型。
- 保留运行日志。
- 人工验收生成的代码。
- 对生产任务启用 Project/Event persistence。
- 发布前执行完整 `pytest -q`。
