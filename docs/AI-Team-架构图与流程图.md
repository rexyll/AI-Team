# AI-Team 架构图与流程图

## 1. 完整逻辑架构图

```mermaid
flowchart TB
    subgraph User[用户层]
        U[Software Requirement]
    end

    subgraph CLI[CLI层]
        M[main.py]
        ARG[Argument Parser]
    end

    subgraph Core[Core 编排层]
        PO[ProjectOrchestrator]
        O[Orchestrator]
        WF[TaskWorkflow]
        WFF[WorkflowFactory]
        PR[ProjectResult]
    end

    subgraph Agent[Agent层]
        P[PlannerAgent]
        AR[ArchitectAgent]
        D[DeveloperAgent x N]
        T[TesterAgent]
        R[ReviewerAgent]
        BA[BaseAgent]
    end

    subgraph Runtime[Runtime层]
        ROUTER[AgentRouter]
        FACTORY[AgentFactory]
        TM[TaskManager]
        STATUS[TaskStatus]
        DS[DependencyScheduler]
        GRAPH[DependencyGraph]
        EXEC[TaskLayerExecutor]
        CTX[AgentContext / ContextBuilder]
        COMPACT[ContextCompactor]
        RESULT[AgentResult / ResultNormalizer]
        RETRY[RetryPolicy]
        METRIC[LLMMetrics]
    end

    subgraph LLM[LLM层]
        BASE[BaseLLM]
        PROVIDER[ProviderLLM]
        CONFIG[Provider/Role Configuration]
        API[OpenAI-compatible API]
    end

    subgraph Tools[工具层]
        REG[ToolRegistry]
        GUARD[ToolArgumentValidation]
        FILE[Filesystem Tools]
        TERM[Terminal Tool]
        GIT[Git Tool]
    end

    subgraph Security[安全层]
        SANDBOX[WorkspaceSandbox]
        POLICY[Permission / Tool Policy]
    end

    subgraph Persistence[持久化层]
        PH[ProjectPersistenceAdapter]
        EH[WorkflowEventLog]
        EP[WorkflowEventPersistenceAdapter]
        AUDIT[ToolExecutionAudit]
        FS[(JSON Files)]
    end

    U --> M --> ARG --> PO
    M --> FACTORY
    FACTORY --> ROUTER
    PO --> P --> PO
    PO --> TM
    PO --> O
    O --> DS
    DS --> GRAPH
    O --> EXEC
    EXEC --> WF
    WF --> ROUTER
    ROUTER --> AR
    ROUTER --> D
    ROUTER --> T
    ROUTER --> R
    AR --> BA
    D --> BA
    T --> BA
    R --> BA
    BA --> CTX
    CTX --> COMPACT
    BA --> BASE
    BASE --> PROVIDER
    PROVIDER --> CONFIG
    PROVIDER --> API
    D --> REG
    REG --> GUARD
    GUARD --> FILE
    GUARD --> TERM
    GUARD --> GIT
    FILE --> SANDBOX
    TERM --> POLICY
    GIT --> POLICY
    TM --> STATUS
    O --> RETRY
    BA --> METRIC
    PO --> PR
    TM --> PH
    WF --> EH
    EH --> EP
    PH --> FS
    EP --> FS
    EP --> AUDIT
```

## 2. 项目级执行时序

```mermaid
sequenceDiagram
    participant U as User
    participant C as CLI
    participant F as AgentFactory
    participant R as AgentRouter
    participant P as Planner
    participant PO as ProjectOrchestrator
    participant TM as TaskManager
    participant O as Orchestrator
    participant W as TaskWorkflow
    participant D as Developer
    participant T as Tester
    participant V as Reviewer

    U->>C: requirement
    C->>F: create_agent_router()
    F->>R: register agents + developer pool
    C->>PO: new ProjectOrchestrator(R)
    PO->>P: run(PLAN-001)
    P-->>PO: validated plan
    PO->>TM: build_task_manager(plan)
    PO->>O: execute(TM)
    O->>TM: compute ready tasks
    O->>W: create_task_workflow(task)
    W->>D: run(task)
    D-->>W: AgentResult + evidence
    W->>T: run(task)
    T-->>W: TEST_PASSED / TEST_FAILED
    alt Tester failed
        W->>D: revision loop
    else Tester passed
        W->>V: run(task)
        alt Reviewer approved
            V-->>W: APPROVED
            W-->>O: task completed
        else Reviewer requires revision
            V-->>W: REVISION_REQUIRED
            W->>D: revision loop
        end
    end
    O-->>PO: all tasks completed/failed/blocked
    PO-->>C: ProjectResult
    C-->>U: final status
```

## 3. 依赖调度流程

```mermaid
flowchart TD
    A[TaskManager tasks] --> B[DependencyScheduler]
    B --> C{Cycle / unknown dependency?}
    C -->|Yes| X[Reject plan / scheduler error]
    C -->|No| D{Dependency failed/blocked?}
    D -->|Yes| E[SchedulerDecision blocked]
    E --> F[TaskManager.mark_blocked]
    D -->|No| G{All dependencies completed?}
    G -->|No| H[Remain pending]
    G -->|Yes| I[Ready]
    I --> J[TaskLayerExecutor]
    J --> K[Parallel task execution]
    K --> A
```

## 4. Developer 工具调用流程

```mermaid
flowchart TD
    A[DeveloperAgent] --> B[BaseAgent._generate_with_tools]
    B --> C[ContextCompactor]
    C --> D[ProviderLLM.generate_with_tools]
    D --> E[LLM tool_call]
    E --> F[ToolRegistry.get/schema]
    F --> G[validate_tool_arguments]
    G --> H{Valid?}
    H -->|No| I[Return tool error to model]
    H -->|Yes| J[Tool implementation]
    J --> K{Filesystem operation?}
    K -->|Yes| L[WorkspaceSandbox.resolve]
    K -->|No| M[Terminal/Git policy]
    L --> N[Tool result]
    M --> N
    N --> O[ToolExecutionHistory]
    O --> P[Append tool result to messages]
    P --> D
    D --> Q{No tool calls?}
    Q -->|Yes| R[Build DeveloperResult]
```

## 5. 质量门禁流程

```mermaid
flowchart LR
    D[Developer completed] --> T[Tester]
    T -->|TEST_FAILED| D
    T -->|TEST_PASSED| R[Reviewer]
    R -->|REVISION_REQUIRED| D
    R -->|APPROVED| C[Completed]
    R -->|Invalid / exception| F[Failure]
    D -->|exception| F
```

## 6. 状态机图

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> ready: dependencies satisfied
    pending --> blocked: dependency failed/missing
    ready --> running
    running --> review_pending: Developer complete
    running --> completed: direct completion path
    running --> failed: execution failure
    review_pending --> reviewing
    review_pending --> running: workflow retry/revision
    reviewing --> completed: reviewer approved
    reviewing --> revision: reviewer requires revision
    reviewing --> failed: reviewer failure
    revision --> running
    failed --> ready: retry policy allows
    blocked --> ready: dependencies repaired
    completed --> [*]
```

## 7. 持久化架构

```mermaid
flowchart TB
    TM[TaskManager] --> PH[ProjectPersistenceAdapter]
    PH --> SNAP[Project Snapshot JSON]
    WF[TaskWorkflow] --> EL[WorkflowEventLog]
    EL --> EP[WorkflowEventPersistenceAdapter]
    EP --> EVT[One JSON per immutable event]
    SNAP --> REC[ProjectSnapshot]
    EVT --> REC2[WorkflowEventLog]
    REC --> R1[resume_persisted]
    REC2 --> R1
    REC --> R2[continue_persisted]
    REC2 --> R2
    REC --> AUD[Audit]
```

## 8. 恢复流程

```mermaid
flowchart TD
    A[continue_persisted(project_id)] --> B[ProjectPersistenceAdapter.load]
    B --> C[Restore Plan]
    B --> D[Restore TaskManager]
    B --> E[Restore ToolExecutionHistory]
    A --> F[WorkflowEventPersistence.load_log]
    C --> G[Rehydrate ProjectOrchestrator]
    D --> G
    E --> G
    F --> G
    G --> H[Attach event persistence]
    H --> I[Execute unfinished tasks]
    I --> J[State checkpoint]
    J --> K[Atomic project snapshot update]
```

## 9. 安全边界图

```mermaid
flowchart LR
    LLM[LLM] --> TC[Tool Call]
    TC --> REG[ToolRegistry]
    REG --> G[Schema Guard]
    G --> P[Permission Boundary]
    P --> S[WorkspaceSandbox]
    S --> FS[(Authorized workspace)]
    S -. deny .-> OUT[(Outside workspace)]
```
