
# AI-Dev-Team 最终代码审查与复杂项目扩展清单

## 一、总体评价

当前项目建议定位为：

**「Production-oriented Multi-Agent Software Engineering Runtime」**

而不是：

**「已经完成所有生产化工作的企业级 AI 软件开发平台」**

当前架构最大的优点是边界已经比较清晰：

```text
User Requirement
       ↓
    Planner
       ↓
      Plan
       ↓
TaskManager ←→ DependencyScheduler
       ↓
 ProjectOrchestrator
       ↓
 TaskWorkflow
       ↓
Developer → Tester → Reviewer
       ↓
    TaskResult
       ↓
 ProjectResult
       ↓
Persistence
       ↓
WorkflowEventLog
       ↓
Projection / Query / Audit
```

同时已经建立了 LLM、Tool、Security、Persistence、Event 等横向边界，这是后续继续扩展的正确方向。

---

# 二、当前代码建议继续完善的项目

## P0：必须优先处理

### [ ] 1. 真正执行 ToolPermissionPolicy，而不是只存在权限模型

当前已经有：

```text
ToolPermissionPolicy
READ
WRITE
EXECUTE
deny-by-default
```

但从实际 DeveloperAgent → ToolRegistry → ToolFunction 的执行链看，目前主要执行的是：

```text
LLM
 ↓
ToolRegistry
 ↓
validate_tool_arguments()
 ↓
tool_function()
```

权限策略并没有成为统一的强制执行中间层。

也就是说：

```text
PermissionPolicy
```

目前更接近一个独立 contract，而不是完整的：

```text
Tool Invocation Authorization Boundary
```

### 建议

增加：

```text
ToolInvocationService
        ↓
Permission Check
        ↓
Argument Validation
        ↓
Sandbox Check
        ↓
Resource Policy
        ↓
Audit
        ↓
Actual Tool
```

以后 DeveloperAgent 不应该直接：

```python
tool_function(**arguments)
```

而应该：

```python
tool_invoker.invoke(
    tool_name=...,
    arguments=...,
    context=...
)
```

这样所有 Agent 都必须经过同一个安全边界。

---

### [ ] 2. Python/Node/Go 等工具执行目前仍然不是“真正的代码沙箱”

这是我认为当前项目最重要的安全问题。

现在 terminal 虽然限制：

* executable allow-list
* shell metacharacter
* command chaining
* `-c`
* encoded command
* 工作目录

但是：

```text
python some_script.py
```

本身就是任意代码执行。

而 DeveloperAgent 又拥有：

```text
write_file
+
run_command
```

因此理论上：

```text
LLM
 ↓
write_file(malicious.py)
 ↓
python malicious.py
```

仍然可以执行 Python 代码。

Python 代码本身可以：

* 访问环境变量
* 读取进程信息
* 创建网络连接
* 调用 subprocess
* 操作工作区
* 消耗 CPU / Memory
* 访问 Python 可用的系统资源

所以现在的 Sandbox 更准确地说是：

> **Path Sandbox + Command Policy**

而不是：

> **Process Sandbox**

### 复杂项目必须升级为：

```text
Developer Agent
      ↓
Execution Broker
      ↓
Container / VM / OS Sandbox
      ↓
Workspace Mount
      ↓
Network Policy
      ↓
CPU Limit
      ↓
Memory Limit
      ↓
Process Limit
      ↓
Timeout
```

Windows-first 环境可以考虑：

* Docker
* Windows Job Object
* 独立 worker process
* 网络隔离
* CPU / Memory quota

这是进入大型复杂项目之前我最建议补齐的一项。

---

# 三、P1：架构层必须完善

## [ ] 3. TaskManager 不应该向外暴露可直接修改的 Task

目前：

```python
task_manager.get_task(...)
```

直接返回：

```python
Task
```

而 Task 内部：

```python
status
context
result
history
dependencies
```

都是可变对象。

这意味着即使 TaskManager 使用了 `RLock`：

```text
TaskManager lock
       ↓
返回 Task
       ↓
外部直接 task.status = ...
```

仍然可以绕过 TaskManager 的状态机。

### 建议

最终变成：

```text
TaskManager
    │
    ├── mutate()
    ├── transition()
    ├── record_result()
    ├── record_feedback()
    │
    └── snapshot()
             ↓
        immutable TaskView
```

Agent 只看到：

```text
TaskSnapshot
AgentContext
```

而不是可以修改的 Runtime Task。

---

## [ ] 4. AgentContext 应该彻底取代 Agent → Task 的直接依赖

现在 BaseAgent 仍然：

```python
run(self, task: Task)
```

虽然已经有：

```python
AgentContext
ContextBuilder
context_view
```

但实际上还是兼容模式。

复杂项目建议最终：

```python
run(self, context: AgentContext) -> AgentResult
```

其中：

```text
AgentContext
├── task snapshot
├── dependency context
├── feedback
├── history
├── artifacts
├── execution metadata
├── tool permissions
└── project information
```

Agent 完全不知道：

```text
TaskManager
Workflow
Persistence
EventLog
```

这样才能真正做到 Agent 与 Runtime 解耦。

---

## [ ] 5. TaskManager 与 DependencyScheduler 存在重复的依赖决策逻辑

目前两边都在判断：

```text
dependency completed?
dependency failed?
dependency blocked?
task ready?
```

例如：

```text
TaskManager.get_ready_tasks()
DependencyScheduler.get_ready_tasks()
DependencyScheduler.decision_for()
```

长期很容易出现：

```text
Scheduler认为Ready
TaskManager认为NotReady
```

### 建议

最终：

```text
DependencyGraph
      ↓
DependencyScheduler
      ↓
SchedulerDecision
      ↓
TaskManager
```

TaskManager 只负责：

```text
状态
历史
生命周期
```

不要再重复实现 dependency policy。

---

## [ ] 6. 增加真正的 Execution / Run ID

现在已经有：

```text
project_id
task_id
execution_id
retry_attempt
event_id
```

但复杂项目还需要：

```text
project_id
run_id
task_id
task_attempt_id
stage_execution_id
tool_execution_id
event_id
```

例如：

```text
PROJECT-001
 └── RUN-004
      ├── TASK-001
      │    ├── ATTEMPT-001
      │    ├── ATTEMPT-002
      │    └── ATTEMPT-003
      │
      └── TASK-002
```

这样才能支持：

* 同一个项目多次运行
* Resume
* Retry
* 用户取消后重新执行
* A/B workflow
* Debug replay
* Execution comparison

---

# 四、Workflow/Event 系统

## [ ] 7. Workflow Event 应增加单调 sequence number

当前 Event 主要依赖：

```text
occurred_at
event_id
task_id
project_id
```

但在高并发下：

```text
timestamp ≠ causal order
```

两个线程完全可能：

```text
T1 occurred_at = 10:00:00.100
T2 occurred_at = 10:00:00.099
```

甚至时钟精度不足时产生相同时间。

### 建议增加：

```text
project_sequence
```

例如：

```text
project_id = P001
sequence = 1001
sequence = 1002
sequence = 1003
```

最终：

```text
Event =

project_id
run_id
sequence
event_id
event_type
task_id
stage
attempt
occurred_at
payload
```

这样 Event Log 才真正具备：

```text
ordered event stream
```

---

## [ ] 8. WorkflowEventLog 当前适合中小规模，不适合超大项目

目前 filesystem persistence 的模型是：

```text
event-001.json
event-002.json
event-003.json
...
```

查询：

```text
glob *.json
↓
全部读取
↓
JSON parse
↓
Python filter
```

这对于：

```text
几十 / 几百 / 几千 events
```

没有问题。

但是复杂项目可能产生：

```text
1 task = 100 events
10,000 tasks = 1,000,000 events
```

此时：

```text
list_for_project()
list_for_task()
QueryService
Projection
```

都会开始明显退化。

### 下一阶段建议：

先升级：

```text
SQLite
```

再根据实际规模升级：

```text
PostgreSQL
```

数据库至少需要：

```text
event_id PK
project_id INDEX
run_id INDEX
task_id INDEX
event_type INDEX
sequence INDEX
occurred_at INDEX
```

---

# 五、Persistence 需要从“Snapshot”升级为“Event + Snapshot”

## [ ] 9. Project Snapshot 不应长期保存全部运行历史

现在 Project Persistence 保存：

```text
project
plan
tasks
result
tool_execution_history
```

随着项目增长：

```text
Task.context
Task.review_history
Task.test_history
tool_execution_history
```

都会越来越大。

每次 checkpoint 都可能重新序列化大量历史数据。

### 建议：

最终采用：

```text
Event Store
     +
Current State Snapshot
     +
Artifact Store
```

例如：

```text
events/
project_snapshot/
artifacts/
```

恢复：

```text
Snapshot
   +
Snapshot之后的Events
   ↓
Current Runtime State
```

这样：

```text
checkpoint
```

不再意味着：

```text
整个项目重新写一遍
```

---

# 六、Artifact 系统必须增加

## [ ] 10. 不要把大型代码/测试/日志全部塞进 Task.context

复杂项目以后一定会遇到：

```text
几十 MB log
大型设计文档
源码 diff
测试报告
coverage.xml
build artifact
binary
screenshots
LLM output
```

不能继续全部：

```python
task.context["xxx"] = huge_string
```

建议增加：

```text
Artifact
├── artifact_id
├── project_id
├── task_id
├── type
├── path
├── size
├── checksum
├── mime_type
├── created_at
└── metadata
```

Task 中只保存：

```text
artifact_id
```

---

# 七、LLM 层继续增强

## [ ] 11. LLM Provider 需要增加统一可靠性层

目前已经完成：

```text
BaseLLM
ProviderLLM
MockLLM
LLM injection
tool calling abstraction
```

这是正确的。

下一步建议统一增加：

```text
LLM Gateway
```

负责：

* timeout
* retry
* exponential backoff
* rate limit
* circuit breaker
* provider fallback
* model fallback
* token budget
* cost accounting
* latency metrics
* request ID
* response ID

最终：

```text
Agent
 ↓
BaseLLM
 ↓
LLMGateway
 ├── Provider A
 ├── Provider B
 ├── Provider C
 └── Local Model
```

而不是 Agent 自己处理 provider failure。

---

## [ ] 12. 增加 Token / Cost Budget

复杂项目一定需要：

```text
Project Budget
Task Budget
Agent Budget
Run Budget
```

例如：

```text
Project:
$20

Planner:
$1

Architect:
$3

Developer:
$10

Reviewer:
$2

Reserve:
$4
```

一旦达到：

```text
token budget
cost budget
tool-call budget
time budget
```

自动停止或降级。

---

# 八、Task 生命周期继续增强

## [ ] 13. 增加 Timeout / Cancellation

目前主要解决：

```text
retry
resume
failure
parallel execution
```

但大型项目一定需要：

```text
RUNNING
   ↓
CANCELLING
   ↓
CANCELLED
```

以及：

```text
deadline
timeout
```

例如：

```text
Task timeout = 10 min
Project timeout = 2 hours
LLM timeout = 120 sec
Tool timeout = 60 sec
```

---

## [ ] 14. Retry Policy 需要区分更多失败类型

当前已经有 FailureKind / RetryPolicy，这是很好的基础。

复杂项目建议进一步区分：

```text
LLM_TIMEOUT
LLM_RATE_LIMIT
LLM_PROVIDER_ERROR
TOOL_TIMEOUT
TOOL_PERMISSION_DENIED
TOOL_EXECUTION_ERROR
VALIDATION_ERROR
QUALITY_GATE_FAILURE
CHECKPOINT_FAILURE
DEPENDENCY_FAILURE
CANCELLED
RESOURCE_EXHAUSTED
```

然后：

```text
retryable?
max_retry?
backoff?
fallback?
```

由策略决定，而不是统一 retry。

---

# 九、Security 需要从“Contract Security”升级到“Runtime Security”

## [ ] 15. 增加 Secret Redaction

目前 Tool Execution Audit 会保存：

```text
arguments
output
error
```

未来很容易出现：

```text
API_KEY
TOKEN
PASSWORD
Authorization
.env 内容
```

被写入：

```text
ToolExecutionHistory
WorkflowEvent
ProjectSnapshot
logs
```

### 必须增加：

```text
SecretRedactor
```

对：

```text
arguments
stdout
stderr
LLM output
event payload
audit record
```

统一脱敏。

---

## [ ] 16. 增加 Secret / Credential 隔离

未来不要让：

```text
os.environ
```

直接成为 Agent 可以间接访问的资源。

建议：

```text
CredentialManager
     ↓
Tool Credential Scope
     ↓
specific tool
```

例如：

```text
git tool → Git credential
github tool → GitHub token
database tool → DB credential
```

Agent 本身不直接看到 credential。

---

# 十、Orchestrator 需要进一步服务化

## [ ] 17. ProjectOrchestrator 目前仍然偏“单进程对象”

现在：

```python
ProjectOrchestrator
```

内部保存：

```text
last_plan
last_task_manager
last_result
workflow_event_log
project_id
```

这种设计非常适合：

```text
CLI
单项目
单进程
```

但大型项目最终需要：

```text
ProjectService
        ↓
ProjectRepository
        ↓
ExecutionService
        ↓
WorkerPool
        ↓
TaskManager
```

不能把：

```text
当前项目状态
```

过多放进 orchestrator 实例本身。

---

# 十一、并行执行需要升级

## [ ] 18. ThreadPoolExecutor 适合当前阶段，但不适合长期的大规模执行

当前：

```text
ThreadPoolExecutor
```

已经可以满足：

```text
bounded parallelism
```

但大型项目以后需要：

```text
Worker Queue
      ↓
Worker Process
      ↓
Task
```

例如：

```text
Project
   ↓
Scheduler
   ↓
Queue
 ┌─┼─┬─┐
 ↓ ↓ ↓ ↓
W1 W2 W3 W4
```

这样可以解决：

* Worker crash
* process isolation
* task timeout
* task cancellation
* worker restart
* resource quota
* horizontal scaling

---

# 十二、增加 CI/CD

## [ ] 19. 建立 GitHub Actions

当前仓库我没有看到针对最新 main 的 GitHub Actions workflow run；GitHub 返回当前 commit 没有关联 workflow run。

建议增加：

```text
.github/workflows/ci.yml
```

至少：

```text
PR
 ↓
ruff
 ↓
mypy
 ↓
pytest
 ↓
security tests
 ↓
performance smoke
```

主分支：

```text
main
 ↓
full pytest
 ↓
release smoke
 ↓
package
 ↓
tag/release
```

---

# 十三、静态质量门禁

## [ ] 20. 正式引入 Ruff

建议：

```text
ruff check
ruff format --check
```

---

## [ ] 21. 正式引入 mypy / pyright

当前项目已经有大量 runtime contract，但 Python 类型复杂度已经开始明显提高。

尤其是：

```text
TaskManager
WorkflowEvent
ProjectPersistence
LLMResponse
LLMToolCall
AgentResult
StageOutcome
SchedulerDecision
```

非常适合通过静态类型进一步固定边界。

---

# 十四、测试体系下一阶段

## [ ] 22. 增加 Property-Based Testing

尤其适合：

```text
DependencyGraph
DependencyScheduler
WorkflowEventLog
Persistence
Task state machine
Retry policy
```

例如随机生成：

```text
1000 个 DAG
```

验证：

```text
no cycle
topological ordering
dependency correctness
```

---

## [ ] 23. 增加真正的大规模压力测试

当前已有：

```text
32
128
512
```

这是非常好的 baseline。

下一阶段建议：

```text
1,000 tasks
5,000 tasks
10,000 tasks
50,000 tasks
```

重点测试：

```text
memory
event count
query latency
checkpoint latency
scheduler latency
startup/recovery latency
```

---

## [ ] 24. 增加 Chaos / Fault Injection

继续扩大：

```text
LLM timeout
LLM disconnect
LLM malformed response
tool timeout
worker crash
process kill
disk full
permission denied
event persistence failure
project persistence failure
network failure
```

尤其要测试：

```text
Kill process
   ↓
Restart
   ↓
Resume
   ↓
No duplicate execution
   ↓
No lost events
```

这会成为真正大型项目的核心能力。

---

# 十五、Planner 还需要从“提示词驱动”升级为“Schema + Policy 驱动”

当前已经针对真实运行发现的问题强化了：

* 用户路径约束
* Agent role mapping
* Developer delivery validation
* Reviewer runnable check

这是正确方向。

但复杂项目不能只依赖 Prompt。

建议：

```text
User Requirement
       ↓
Requirement Parser
       ↓
Requirement Constraints
       ↓
Planner
       ↓
Plan Schema Validation
       ↓
Plan Policy Validation
       ↓
Task Graph
```

例如显式约束：

```text
output_dir
language
framework
platform
deadline
security_level
test_requirement
deployment_requirement
```

应该进入结构化：

```json
{
  "constraints": {
    "platform": "windows",
    "language": "python",
    "output_dir": "workspace/demo",
    "must_have_tests": true
  }
}
```

而不是只存在 Prompt。

---

# 十六、质量门禁还需要增加“交付验收 Agent / Stage”

当前：

```text
Developer
 ↓
Tester
 ↓
Reviewer
```

已经很好。

复杂项目建议增加：

```text
Developer
 ↓
Tester
 ↓
Reviewer
 ↓
Acceptance
```

Acceptance 专门验证：

```text
需求是否全部满足
文件是否全部存在
CLI 是否能运行
安装是否成功
README 是否正确
输出路径是否正确
API 是否符合要求
测试是否通过
```

也就是说：

```text
Reviewer = Code Quality
Acceptance = Product Requirement
```

两者不要混在一起。

---

# 十七、建议增加 Project Manifest

复杂项目应该存在：

```text
project.yaml
```

或：

```text
ProjectManifest
```

内容包括：

```text
project_id
project_name
version
requirement
constraints
platform
language
workspace
budget
timeout
max_workers
max_retries
llm_policy
tool_policy
security_policy
artifact_policy
```

这样项目执行参数不再散落在：

```text
AgentConfig
ProjectOrchestrator
Task
environment variables
```

---

# 十八、最终建议的下一代架构

如果下一步准备真正挑战复杂项目，我建议把 AI-Dev-Team 演进成下面这个架构：

```text
                    ┌─────────────────────┐
                    │    User / API / CLI │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Project Service   │
                    └──────────┬──────────┘
                               │
                     Requirement Model
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Planner / Plan      │
                    │ Validator / Policy  │
                    └──────────┬──────────┘
                               │
                         Task Graph
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Dependency Scheduler│
                    └──────────┬──────────┘
                               │
                           Task Queue
                               │
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
        ┌─────────┐       ┌─────────┐       ┌─────────┐
        │ Worker 1│       │ Worker 2│       │ Worker N│
        └────┬────┘       └────┬────┘       └────┬────┘
             │                 │                 │
             └─────────────────┼─────────────────┘
                               │
                        Agent Runtime
                               │
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                 ▼
          Agent             Agent             Agent
             │                 │                 │
             └─────────────────┼─────────────────┘
                               │
                         LLM Gateway
                               │
                 ┌─────────────┼─────────────┐
                 ▼             ▼             ▼
             Provider A    Provider B    Local Model


                    Tool Invocation Service
                              │
                ┌─────────────┼─────────────┐
                ▼             ▼             ▼
             Permission     Sandbox      Audit
                │             │             │
                └─────────────┼─────────────┘
                              ▼
                      Isolated Execution


                 ┌───────────────────────────┐
                 │      Event Store          │
                 │ Project / Run / Task      │
                 │ Sequence / Event          │
                 └─────────────┬─────────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
             Snapshot       Query          Audit
                │
                ▼
             Recovery


                 ┌───────────────────────────┐
                 │      Artifact Store       │
                 │ source / logs / reports   │
                 │ diff / test / binaries    │
                 └───────────────────────────┘
```

---

# 十九、建议的后续开发优先级

## Phase 9：Architecture Debt Cleanup

* [ ] TaskManager mutable-state isolation
* [ ] AgentContext 完全迁移
* [ ] Scheduler / TaskManager 职责收敛
* [ ] AgentResult / StageOutcome / TaskStatus 统一状态模型
* [ ] AgentConfig 强类型校验
* [ ] WorkflowEvent sequence
* [ ] Project/Run/Attempt ID 完整化

## Phase 10：Secure Execution Runtime

* [ ] ToolInvocationService
* [ ] PermissionPolicy 强制接入
* [ ] Tool capability model
* [ ] Secret redaction
* [ ] Credential isolation
* [ ] Process sandbox
* [ ] CPU / memory / process quota
* [ ] Network isolation
* [ ] Tool timeout / cancellation

## Phase 11：Scalable Persistence

* [ ] SQLite Event Store
* [ ] Event sequence
* [ ] Event indexes
* [ ] Incremental checkpoint
* [ ] Snapshot + Event replay
* [ ] Artifact Store
* [ ] Large-output storage
* [ ] Retention / compaction

## Phase 12：Reliable LLM Runtime

* [ ] LLM Gateway
* [ ] timeout
* [ ] retry/backoff
* [ ] circuit breaker
* [ ] provider fallback
* [ ] model routing
* [ ] token budget
* [ ] cost accounting
* [ ] structured output
* [ ] response validation

## Phase 13：Distributed Execution

* [ ] Task Queue
* [ ] Worker Process
* [ ] Worker heartbeat
* [ ] worker crash recovery
* [ ] task lease
* [ ] task cancellation
* [ ] task timeout
* [ ] distributed locking
* [ ] horizontal scaling

## Phase 14：Enterprise Quality

* [ ] API Server
* [ ] Authentication
* [ ] Multi-project isolation
* [ ] RBAC
* [ ] Project quota
* [ ] User quota
* [ ] Cost dashboard
* [ ] Execution dashboard
* [ ] Event tracing
* [ ] OpenTelemetry
* [ ] CI/CD
* [ ] Release automation

---

# 二十、我认为现在最值得立即做的 10 项

如果不想一次做太多，我建议严格按下面顺序：

1. [ ] **ToolInvocationService + PermissionPolicy 强制接入**
2. [ ] **真正的代码执行 Sandbox**
3. [ ] **TaskManager / AgentContext 状态隔离**
4. [ ] **Project / Run / TaskAttempt / Event Sequence ID**
5. [ ] **Workflow Event causal ordering**
6. [ ] **Timeout + Cancellation**
7. [ ] **Artifact Store**
8. [ ] **SQLite Event Store + Snapshot/Replay**
9. [ ] **LLM Gateway + Budget + Retry/Fallback**
10. [ ] **Worker Process / Queue 化**

---

# 二十一、最终结论

我对当前 AI-Dev-Team 的评价是：

| 能力                 | 当前水平 |
| -------------------- | -------- |
| Agent 架构           | ★★★★☆    |
| Workflow             | ★★★★☆    |
| Dependency Scheduler | ★★★★☆    |
| Retry / Resume       | ★★★★☆    |
| LLM 抽象             | ★★★★☆    |
| Tool Registry        | ★★★★☆    |
| 基础 Sandbox         | ★★★☆☆    |
| 真正执行隔离         | ★★☆☆☆    |
| Persistence          | ★★★☆☆    |
| Event System         | ★★★★☆    |
| Audit / Query        | ★★★★☆    |
| 并发                 | ★★★★☆    |
| 测试体系             | ★★★★★    |
| 真实 LLM 验证        | ★★★★☆    |
| 大规模运行能力       | ★★☆☆☆    |
| 服务化能力           | ★★☆☆☆    |
| 企业级安全           | ★★☆☆☆    |

**所以我不建议继续无止境地给当前代码增加“小功能”。**

当前最合适的阶段转换应该是：

```text
Phase 0–8
基础 Runtime 建设
        ↓
当前版本
        ↓
Phase 9
架构债务清理
        ↓
Phase 10
Secure Execution Runtime
        ↓
Phase 11
Scalable Persistence
        ↓
Phase 12
Reliable LLM Runtime
        ↓
Phase 13
Distributed Execution
        ↓
Phase 14
Enterprise / Service Platform
```

尤其值得强调的是：当前项目已经通过了相当完整的 contract、failure injection、并发、性能和真实 Provider 闭环验证；最新 DevPlan 也已经明确指出，后续真正的风险已经从“功能是否正确”转向**规模、资源、并发、取消/恢复、性能和生产安全边界**。

因此，我建议把当前版本**冻结为一个稳定基线**，不要再大幅修改现有核心 Workflow 语义。下一阶段直接建立 **Phase 9「Complex Project Readiness」**，优先解决上面前 10 项。这样以后拿它去开发大型项目时，不需要反复推翻现在已经稳定下来的 Runtime。
