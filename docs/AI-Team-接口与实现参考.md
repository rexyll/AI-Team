# AI-Team 接口与实现参考

## 1. CLI 接口

### `main.py`

```text
python main.py <requirement> [--projects-base <path>]
```

核心函数：

```python
build_parser() -> argparse.ArgumentParser
run_project(requirement: str, *, projects_base: str | None = None)
main() -> int
```

实现链：

`main → run_project → create_agent_router → ProjectOrchestrator.create_plan → build_task_manager → execute`

## 2. ProjectOrchestrator

文件：`core/project_orchestrator.py`

核心接口：

```python
create_plan(requirement: str) -> dict[str, Any]
build_task_manager(plan: dict[str, Any]) -> TaskManager
create_orchestrator(task_manager: TaskManager) -> Orchestrator
execute(task_manager: TaskManager, *, state_change_hook=None) -> ProjectResult
run(requirement: str) -> ProjectResult
resume(task_manager: TaskManager | None = None) -> ProjectResult
resume_persisted(project_id, adapter, *, event_persistence=None) -> ProjectResult
continue_persisted(project_id, adapter, *, event_persistence=None) -> ProjectResult
audit_persisted(project_id, adapter) -> ToolExecutionAudit
audit_consistency_persisted(project_id, adapter) -> dict[str, Any]
```

实现要点：

- `create_plan()` 强制取得 planner role，并验证 Planner 输出。
- `build_task_manager()` 通过 PlanBuilder 将 JSON plan 转换为 Task 对象。
- `execute()` 创建 Orchestrator 并注入 WorkflowEventLog。
- `continue_persisted()` 先恢复 snapshot，再以 `state_change_hook` 做状态边界持久化。

## 3. Orchestrator

文件：`core/orchestrator.py`

核心接口：

```python
run() -> None
set_state_change_hook(hook) -> None
set_workflow_event_log(log, *, project_id=None) -> None
```

关键实现：

1. `DependencyScheduler` 计算 ready/blocked。
2. `TaskLayerExecutor` 执行当前层。
3. Developer 任务交给 `TaskWorkflow`。
4. 非 Developer 任务直接调用对应 Agent 并完成 Task。
5. 异常经过 `FailureKind` 分类与 RetryPolicy。
6. checkpoint failure 被包装成 `_CheckpointFailure`，避免把持久化故障错误解释为业务 Task failure。

## 4. TaskManager

文件：`runtime/task_manager.py`

TaskManager 是生命周期的唯一写边界。

主要接口：

```python
get_task(task_id) -> Task
get_all_tasks() -> list[Task]
transition(task_id, target_status) -> Task
get_ready_tasks() -> list[Task]
ensure_executable(task_id) -> Task
mark_ready(task_id) -> Task
mark_running(task_id) -> Task
mark_completed(task_id, result=None) -> Task
mark_failed(task_id, error) -> Task
mark_blocked(task_id, error) -> Task
retry_task(task_id, *, reason, retryable) -> Task
record_result(task_id, result) -> Task
record_test_result(task_id, test_result) -> Task
record_review_result(task_id, review_result, *, increment_round=True) -> Task
set_feedback(task_id, source, feedback) -> Task
```

实现原则：Workflow 负责“发生了什么”，TaskManager 负责“这个状态转换是否合法”。

## 5. AgentRouter

文件：`runtime/agent_router.py`

```python
register(agent_or_role, agent=None) -> None
register_developer_pool(agents: list[object]) -> None
get_agent(role: str) -> object | None
get_developers() -> list[object]
get_developer_for_task(task_id: str) -> object
route(role: str) -> object
has_agent(role: str) -> bool
list_agents() -> dict[str, object]
```

Developer pool 选择算法：

```text
SHA256(task_id) → first 8 bytes → integer → modulo pool size
```

## 6. BaseAgent

文件：`agents/base.py`

抽象接口：

```python
@property
role -> str

build_context(task, *, all_tasks=None) -> AgentContext
_generate(prompt, *, system_prompt="", temperature=0.2, max_tokens=4096) -> str
_generate_with_tools(messages, *, tools=None, tool_choice="auto") -> LLMResponse
metrics_snapshot()
run(task: Task) -> AgentResult
```

`_generate()` 和 `_generate_with_tools()` 都先经过 ContextCompactor，并记录 LLMMetrics。

## 7. Agent Result

标准结构：

```json
{
  "status": "completed",
  "agent": "developer",
  "task_id": "TASK-001",
  "message": "...",
  "data": {}
}
```

Workflow 通过 `normalize_agent_result()` 将 legacy dict 和 AgentResult 统一成标准 AgentResult。

## 8. Developer 接口与实现

Developer 使用：

```python
TOOL_REGISTRY.schemas()
```

向 LLM 提供 function-call schema，然后循环处理 `LLMToolCall`。

每个工具调用依次执行：

```text
JSON parse
→ arguments dict check
→ registry lookup
→ schema validation
→ tool function
→ evidence recording
→ ToolExecutionHistory
→ append tool result to messages
```

Developer 最大 50 次工具循环。

无任何 tool call、file change、command execution 时返回 failed，避免虚假完成。

## 9. Tester 接口

```python
run(task: Task) -> AgentResult
```

Tester 的 `_parse_result()` 将模型文本转换为：

- `passed`
- `failed`

没有合法 verdict 会抛出 ValueError，Workflow 再依据 invalid verdict policy 进行重试/失败处理。

## 10. Reviewer 接口

```python
run(task: Task) -> AgentResult
```

Reviewer 的 `_parse_review_result()` 将文本转换为：

- `approved`
- `revision`

Reviewer 会对 Developer Result 做结构化压缩，而不是把任意长度的开发报告原样发送给模型。

## 11. BaseLLM

文件：`runtime/llm/base.py`

```python
generate(prompt, *, system_prompt="", temperature=0.2, max_tokens=4096) -> str
generate_with_tools(messages, *, tools=None, tool_choice="auto") -> LLMResponse
```

`LLMResponse`：

```python
@dataclass(frozen=True)
class LLMResponse:
    content: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
```

## 12. ProviderLLM

文件：`runtime/llm/provider.py`

ProviderLLM 将 BaseLLM 映射到 OpenAI-compatible `chat.completions.create()`。

`generate()` 创建 system/user messages。

`generate_with_tools()` 将工具 schema 传递给 provider，并将 provider tool_calls 转换为 provider-neutral `LLMToolCall`。

Transient status：`429/500/502/503/504`。

## 13. ToolRegistry

文件：`tools/registry.py`

当前注册工具：

```text
list_files
read_file
write_file
move_file
delete_file
run_command
git_command
```

注册要求：

- name 非空
- implementation callable
- schema dict
- schema.function.name 必须与 name 相同
- 不允许重复注册

## 14. Tool Guard

文件：`security/tool_guard.py`

Schema 模式验证：

- arguments 必须 object
- properties 必须 object
- required 必须 list
- 禁止 unknown arguments
- 禁止缺 required argument
- 校验 JSON primitive/object/array 类型

验证失败抛 `ToolArgumentValidationError`。

## 15. WorkspaceSandbox

文件：`security/workspace.py`

核心接口：

```python
resolve(path) -> Path
require_file(path) -> Path
require_directory(path) -> Path
```

实现通过 `Path.resolve()` + `relative_to(root)` 判断最终路径是否在授权根目录内。

## 16. WorkflowEvent

文件：`runtime/workflow_event.py`

```python
@dataclass(frozen=True)
class WorkflowEvent:
    event_id: str
    event_type: str
    project_id: str
    occurred_at: str
    task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
```

对象 immutable，payload 必须 JSON serializable。

## 17. WorkflowEventLog

接口：

```python
append(event)
append_if_absent(event) -> bool
merge(events) -> int
list_all() -> list[WorkflowEvent]
list_for_project(project_id) -> list[WorkflowEvent]
list_for_task(task_id) -> list[WorkflowEvent]
get(event_id) -> WorkflowEvent
to_dict() -> list[dict]
from_dict(payload) -> WorkflowEventLog
```

若绑定 persistence sink，新事件先 durable write，成功后才加入 memory index。

## 18. WorkflowEventPersistenceAdapter

文件：`runtime/workflow_event_persistence.py`

```python
save(event)
save_if_absent(event) -> bool
save_if_absent_many(events) -> int
load(event_id) -> WorkflowEvent
load_log() -> WorkflowEventLog
list_all()
list_for_project(project_id)
list_for_task(task_id)
list_ids()
delete(event_id)
```

采用每事件一个 JSON 文件，event_id 文件名安全校验，并通过 temp file + fsync + atomic publish 保证写入边界。

## 19. ProjectPersistenceAdapter

文件：`runtime/project_persistence.py`

```python
save(project_id, *, plan, task_manager, result=None, tool_execution_history=None)
update(project_id, *, plan, task_manager, result=None, tool_execution_history=None)
checkpoint(project_id, *, plan, task_manager, result, tool_execution_history=None)
load(project_id) -> ProjectSnapshot
list_ids() -> list[str]
delete(project_id)
audit(project_id) -> ToolExecutionAudit
audit_consistency(project_id) -> dict[str, Any]
```

## 20. 配置接口

文件：`config/model.py`

```python
declared_provider_names() -> list[str]
get_provider_profile(name=None) -> ProviderProfile
get_client_for(profile_name=None)
resolve_role_llm_spec(role) -> tuple[str, str]
get_developer_count() -> int
resolve_developer_llm_spec(index) -> tuple[str, str]
ask_ai(prompt, system_prompt=None) -> str
```

## 21. 配置对象

`AgentConfig`：

```python
@dataclass(frozen=True)
class AgentConfig:
    role: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 4096
    enabled: bool = True
    system_prompt: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
```

## 22. 实现关系总结

```text
main.py
  ↓
ProjectOrchestrator
  ├─ PlannerAgent
  ├─ PlanBuilder
  ├─ TaskManager
  └─ Orchestrator
       ├─ DependencyScheduler
       ├─ TaskLayerExecutor
       └─ TaskWorkflow
            ├─ DeveloperAgent
            │    ├─ BaseAgent
            │    ├─ ProviderLLM
            │    └─ ToolRegistry → ToolGuard → Sandbox
            ├─ TesterAgent
            └─ ReviewerAgent

ProjectOrchestrator / Workflow
  ├─ WorkflowEventLog → WorkflowEventPersistenceAdapter
  └─ ProjectPersistenceAdapter
```
