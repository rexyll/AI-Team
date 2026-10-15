# AI-Team 部署与运维手册

> 适用代码基线：`main` / 2026-10-15 逆向文档基线

## 1. 支持环境

当前项目按仓库文档定义，官方开发环境为 Windows 11 + Python 3.14。Git 必需；Docker 和 VS Code 为可选工具。项目以源码树方式运行，不要求构建 wheel。

## 2. 获取代码

```powershell
git clone https://github.com/rexyll/AI-Team.git
cd AI-Team
```

如果使用现有工作区，确保从仓库根目录执行命令。

## 3. 创建虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

应为 Python 3.14。PowerShell 如果禁止执行脚本，可以直接使用 `.venv\Scripts\python.exe`，不建议为了项目修改系统执行策略。

## 4. 安装依赖

```powershell
pip install -r requirements.txt
```

当前核心声明依赖包括 OpenAI SDK 与 python-dotenv。安装后验证：

```powershell
python -m pytest --version
```

## 5. 配置 LLM Provider

复制 `.env.example` 为 `.env`。Provider 使用 OpenAI-compatible API。

最小概念配置：

```ini
DEFAULT_PROVIDER=agnes
AGNES_API_KEY=your-key
AGNES_BASE_URL=https://your-openai-compatible-endpoint/v1
AGNES_MODEL=your-model
```

也可以声明多个 Provider：

```ini
LLM_PROVIDERS=agnes,openrouter
DEFAULT_PROVIDER=agnes

AGNES_API_KEY=...
AGNES_BASE_URL=https://...
AGNES_MODEL=...

OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://...
OPENROUTER_MODEL=...
```

角色可以独立绑定：

```ini
PLANNER_PROVIDER=agnes
PLANNER_MODEL=model-a
ARCHITECT_PROVIDER=agnes
ARCHITECT_MODEL=model-a
DEVELOPER_PROVIDER=openrouter
DEVELOPER_MODEL=model-b
TESTER_PROVIDER=agnes
TESTER_MODEL=model-a
REVIEWER_PROVIDER=agnes
REVIEWER_MODEL=model-c
```

Developer pool：

```ini
DEVELOPER_COUNT=2
DEVELOPER_1_PROVIDER=agnes
DEVELOPER_1_MODEL=model-a
DEVELOPER_2_PROVIDER=openrouter
DEVELOPER_2_MODEL=model-b
```

## 6. 配置解析验证

不发送网络请求的验证：

```powershell
python -c "from config.model import resolve_role_llm_spec; print([resolve_role_llm_spec(r) for r in ('planner','developer','tester','reviewer')])"
```

真实 provider client 验证：

```powershell
python -c "from config.model import get_client_for; get_client_for('agnes'); print('provider config OK')"
```

客户端是惰性创建的，因此配置对象解析成功并不等于 API Key 已经可以完成真实调用。

## 7. 基线测试

在真实运行前执行：

```powershell
pytest -q
```

项目把完整 pytest 作为开发节点的最终 acceptance gate。当前仓库 README 记录的生产强化阶段已经覆盖真实 OpenAI-compatible provider 的端到端验证。

## 8. 启动

最简单的 CLI：

```powershell
python main.py "开发一个个人记账命令行工具，所有文件放在 workspace/expense/ 目录下"
```

指定项目 sandbox 基础目录：

```powershell
python main.py --projects-base D:\AIProjects "开发一个温度转换工具"
```

注意参数顺序：requirement 是位置参数；PowerShell 下推荐从仓库根目录运行。

## 9. 工作区隔离

默认工作区根由 `security.workspace.PROJECT_ROOT` 定义为仓库之外的 `projects/`。Developer 的 `list_files/read_file/write_file/move_file/delete_file` 都经过 `resolve_workspace_path()`。

如果需求明确指定输出目录，例如：

```text
所有文件放在 workspace/stringkit/ 目录下
```

CLI 会提取路径约束，并把 sandbox root 锚定到 `projects/workspace/`，模型写 `stringkit/...` 时最终落到 `projects/workspace/stringkit/...`。

因此生成物默认不会污染 AI-Team 源码仓库。

## 10. 运行日志

PowerShell 可以保存完整日志：

```powershell
python main.py "..." *>&1 | Tee-Object -FilePath runs\run-001.log
```

CLI 已对 stdout/stderr 做不可编码字符替换处理，以降低 Windows 本地 code page 对中文/特殊字符日志的影响。

## 11. 运行时参数

### LLM

| 变量 | 默认 | 作用 |
|---|---:|---|
| `LLM_MAX_ATTEMPTS` | 4 | Provider transient/empty response 最大尝试次数 |
| `LLM_BACKOFF_SECONDS` | 2 | Provider 指数退避基数 |
| `LLM_INVALID_VERDICT_ATTEMPTS` | 2 | Tester/Reviewer 非法 verdict 的额外尝试 |
| `REVIEWER_MAX_DEVELOPER_RESULT_CHARS` | 16000 | Reviewer 输入 Developer Result 上限 |
| `DEVELOPER_COUNT` | 1 | Developer pool 数量 |

### Workflow

| 参数 | 默认 | 作用 |
|---|---:|---|
| `MAX_TOOL_ITERATIONS` | 50 | Developer 单任务工具循环上限 |
| `MAX_REVIEW_ROUNDS` | 3 | TaskWorkflow 最大 Developer/Test/Review 轮次 |

## 12. 持久化部署

CLI 默认执行是内存态；如果需要 durable runtime，应显式构造：

```python
from runtime.project_persistence import ProjectPersistenceAdapter
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter

project_store = ProjectPersistenceAdapter("./data/projects")
event_store = WorkflowEventPersistenceAdapter("./data/events")
```

Project persistence 保存整个项目快照；Event persistence 保存不可变 WorkflowEvent。

推荐目录：

```text
AI-Team/
├── data/
│   ├── projects/
│   │   └── PROJECT-001.json
│   └── events/
│       ├── <event-id>.json
│       └── ...
└── runs/
    └── run-001.log
```

## 13. 恢复

### 13.1 仅恢复快照

```python
orchestrator.resume_persisted(
    "PROJECT-001",
    project_store,
    event_persistence=event_store,
)
```

该操作恢复内存对象，不自动继续执行。

### 13.2 继续未完成工作

```python
orchestrator.continue_persisted(
    "PROJECT-001",
    project_store,
    event_persistence=event_store,
)
```

该操作恢复快照并继续未完成任务，同时在状态变化边界更新 project snapshot。

## 14. 审计与一致性检查

```python
orchestrator.audit_persisted("PROJECT-001", project_store)
orchestrator.audit_consistency_persisted("PROJECT-001", project_store)
```

`audit_consistency_persisted()` 用于比较 canonical ToolExecutionHistory 与 Task.context 内的历史，识别缺失或冲突 execution_id。

## 15. 备份策略

由于 Project snapshot 和 Workflow Event 都是 JSON 文件，建议：

1. 定期备份 `data/projects/`。
2. 定期备份 `data/events/`。
3. 运行日志单独归档。
4. 不把 `.env`、API key 或 token 放入备份仓库。
5. 恢复前先复制当前数据目录，保留原始现场。

## 16. 故障排查

### 16.1 Provider 配置错误

典型错误：`No LLM provider is configured`、`<PROVIDER>_BASE_URL is not configured`、`<PROVIDER>_API_KEY is not configured`。

处理顺序：

1. 检查 `.env` 是否在仓库根目录。
2. 检查 Provider 名称大小写。
3. 执行 `resolve_role_llm_spec`。
4. 再执行 `get_client_for`。
5. 最后运行真实任务。

### 16.2 Planner 多次失败

如果出现 `Planner 在多次尝试后仍无法生成合法计划`：

- 检查模型是否能稳定生成 JSON。
- 缩短或明确需求。
- 检查任务角色和 dependency 是否合理。
- 检查路径约束是否写清楚。

### 16.3 Developer 长时间运行

Developer 最多 50 次工具迭代。长时间运行通常意味着任务过大、模型在反复探索或测试失败后持续修复。应先缩小需求，再观察 tool execution history。

### 16.4 Tester FAILED

Tester 不负责修复。查看 Developer Result 的 `tests`、`files_changed`、`validation`，以及 Tester feedback。若结论正确，下一轮会重新进入 Developer。

### 16.5 Reviewer REVISION_REQUIRED

这是正常质量门禁行为。Reviewer feedback 会写入 Task context，下一轮 Developer 可以直接读取上一轮意见。

### 16.6 没有 Ready Task

检查：

- dependency 是否存在。
- 是否形成循环依赖。
- 上游任务是否 failed/blocked。
- TaskManager 状态是否符合预期。

## 17. 安全运维要求

- API key 只放环境变量/安全凭据，不入 Git。
- 不扩大 WorkspaceSandbox root 来“解决”模型访问问题。
- 不绕过 ToolGuard。
- 不让 Developer 直接获得任意 shell/filesystem API。
- 生产环境启用持久化时，应限制 data 目录权限。
- Event 冲突不能通过覆盖文件解决，应调查 event_id 重用原因。

## 18. 发布前检查清单

- [ ] Python 版本正确
- [ ] `pip install -r requirements.txt` 成功
- [ ] `pytest -q` 全绿
- [ ] `.env` 配置正确且未提交
- [ ] Provider 解析成功
- [ ] 最小真实任务成功
- [ ] Developer 产物位于预期 sandbox
- [ ] Tester/Reviewer verdict 合法
- [ ] 若启用持久化，project/event store 可写
- [ ] 恢复流程已验证
- [ ] 审计一致性检查通过
