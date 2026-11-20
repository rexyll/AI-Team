# Local Docker 同步操作完成证明设计

> 状态：设计决策完成；实现与 CI 验收尚未开始。  
> 日期：2026-11-20  
> 适用范围：仅 `docker-local` + `LocalDockerRouterReplacementProvider`。

## 1. 背景与要解决的问题

当前恢复证据链已有 Host-owned provider-call receipt sidecar：

`<deployment-history-stem>.provider-operations.sqlite3`

`HostDeploymentReplacementManager._invoke_provider_operation()` 在调用 provider 前写入 `started`，provider 方法返回结构化 `DeploymentOperationResult` 后写入 `returned`；异常、无效返回或身份不匹配写入 `indeterminate`。receipt 按 provider/project/environment/operation/action 唯一约束，并绑定请求摘要与返回结果摘要。

但 `LocalDockerProvider.inspect_operation()` 明确返回 `unsupported`。这一点必须保留：Docker Engine 并没有提供以 AI-Team replacement `operation_id` 和 action 为键的 provider-owned durable operation resource。Host receipt 不能被伪装成 Docker operation ID，也不能被称为 provider API 的异步终态观察。

当前缺口是：本仓库的 Local Docker replacement adapter 并不提交云端异步 job。它通过固定 argv 调用 Docker 和 HAProxy Runtime API，并在方法返回前完成必要的 inspect/read-back 与 Host registry 提交。因此，对限定的两类恢复决策，可以评估一个不同的证明类型：**Host 同步方法调用完成见证**，并且必须与独立、实时的 Docker runtime 和 Router/HAProxy 后置条件同时成立。

## 2. 决策

### 2.1 保留 provider-native 能力边界

- `LocalDockerProvider.inspect_operation()` 继续返回 `unsupported`。
- 不把 Host receipt 的 `returned` 转换成伪造的 provider operation ID。
- 不修改通用 `DeploymentProviderOperationInspector` 的语义，不让云 Provider 或未来异步 Provider 继承本地同步假设。
- 新增独立类型/接口，名称应明确为 Host synchronous operation completion，而不是 provider operation inspection。
- 通用 reconciliation evidence 使用中性的 `operation_completion` 证据类型，以区分“provider-native operation inspection”和“Host synchronous method completion”。

### 2.2 只允许两个恢复动作使用该模型

| Reconciliation 决策 | 必须找到的 Host action receipt | receipt 成功条件 | 独立后置条件 |
|---|---|---|---|
| `abort_candidate` | `abort_candidate` | 精确 scope/action 的 `returned`，Provider result 为 `succeeded`，请求和响应摘要有效 | 候选 immutable runtime ID 权威 not-found；previous immutable runtime ID verified/running/healthy；Router registry、live selector 和 effective target 均确认 previous runtime |
| `confirm_previous_retired` | `retire_previous` | 精确 scope/action 的 `returned`，Provider result 为 `succeeded`，请求和响应摘要有效 | candidate immutable runtime ID verified/running/healthy 且是 Router effective target；previous immutable runtime ID 被权威确认 exited/dead |

不能只凭 receipt 作出任何恢复结论。若 runtime 或 route read-back 不满足表中任意一项，即使 receipt 是 `returned/succeeded` 也必须拒绝。

### 2.3 为什么只接受 succeeded

`abort_candidate` / `retire_previous` 在中途发生局部副作用后，可能返回 `failed`：例如容器停止后 Host Router registry 提交失败。虽然某些情况下实时状态可能看起来接近目标状态，但失败返回无法证明该同步方法已完成其完整的 Host-side 契约。第一版因此只接受 `provider_result_status == succeeded`。失败、unavailable、unsupported、started、indeterminate 均保持人工处理，不做推断。

这是有意保守的选择；后续若需支持“失败但状态已满足”的补偿流程，应另行定义其精确 postcondition 和审计决策，不得放宽当前成功规则。

## 3. 当前实现中可作为同步边界的事实

本模型只适用于当前 Local Docker Router replacement adapter，原因是以下方法的现有实现都在返回前等待自身的同步动作与 read-back：

- `start_candidate`：确保 routed app 已创建，读取 immutable container ID、network/endpoint 和 fresh HEALTHCHECK，再准备 inactive HAProxy slot，回读 backend state/endpoint，并提交 Host Router registry。
- `switch_traffic`：由 HAProxy Runtime API 更新 active-slot map；slot manager 校验 live selector/effective target，随后提交 Router registry。方法不会把后台 job ID 返回给调用者。
- `retire_previous`：等待旧 backend drain；只有确认 `scur == 0` 才继续；按 immutable container ID stop，并 inspect 确认 exited/dead；最后提交移除旧 slot 的 Router registry。
- `abort_candidate`：排空 inactive candidate slot；按 immutable container ID stop 并 inspect 确认停止；再提交 Router registry。

此处“同步”只描述 Host 调用边界：方法返回时，本地 Docker CLI/HAProxy Runtime API 调用及代码内的 read-back 已结束。它不声称 Docker daemon 或 HAProxy 提供了跨系统分布式事务，也不消除方法执行期间的崩溃窗口。任何 provider 方法若改成启动后台 job 后立即返回，必须撤销该动作的 synchronous eligibility。

## 4. Receipt 检查必须绑定到 journal，不接受调用方自报

新增只读 inspector 应由 Host 从现有 history 路径派生 sidecar 路径，并以 `mode=ro` 打开。读取路径不得创建目录、数据库、表、receipt 或 Router 资源。

每次读取均须同时校验：

1. journal 的 provider/project/environment/operation_id 精确匹配；
2. action 与 reconciliation 决策固定映射：`abort_candidate → abort_candidate`，`confirm_previous_retired → retire_previous`；
3. receipt 行的完整 scope/action 与请求完全一致；
4. receipt 的 `state == returned`，`provider_result_status == succeeded`；
5. `started_at`、`completed_at` 均为 timezone-aware，且 `started_at <= completed_at <= snapshot read start`；
6. receipt 时间在配置的新鲜度窗口内，不允许未来时间戳；
7. 请求摘要必须由 inspector 根据 journal 中的 immutable IDs 重新计算，不能信任数据库行内的摘要：
   - abort：`candidate_deployment_id=target_deployment_id`、`candidate_runtime_id=candidate_runtime_id`、`previous_runtime_id=previous_runtime_id`；
   - retire：`previous_deployment_id=previous_deployment_id`、`previous_runtime_id=previous_runtime_id`；
8. 响应摘要必须为有效 SHA-256；缺少 sidecar、row、字段、数据库损坏或任意 scope/digest/action 不匹配均 fail-closed。

receipt 中的响应摘要来自 `DeploymentOperationResult` 的有界、脱敏投影。它只用于把 Host 已记录的返回值绑定到本次 completion witness；不能代替实际 runtime/route observation。

## 5. Evidence 与信任边界

- 新证据必须显式标识 `host_synchronous_call_receipt`（或等价 source kind），不能沿用会误导为 provider API 的标签。
- 证据摘要应包含 provider/project/environment/operation_id/action、request digest、response digest、receipt timestamps、receipt-store source identity 和 completion type。
- source authenticator 只能断言证据来自当前 Host 配置的 receipt sidecar；该断言依赖 Host 文件访问控制和运行环境的本机信任边界。
- 本地 SQLite 文件不是防御 Host 管理员篡改的密码学审计锚点。不得声称它具有远端签名、不可抵赖或跨主机一致性。外部 trusted-head anchoring、远端 retention 和多主机事务锁仍是独立生产门槛。
- runtime/route 证据继续使用已配置的 Docker daemon pin，并在每次读取时验证 daemon identity、exact immutable runtime ID、Router identity、selector、effective target、backend endpoint 和 UP 状态。
- Snapshot reader 继续在 evidence collection 前后读取同一 journal revision；revision 变化、source authentication 失败、证据超时/过期或任何 read-back 不一致均拒绝整个 snapshot。

## 6. 必须覆盖的测试矩阵

| 类别 | 测试要求 |
|---|---|
| 正向 abort | 只接受 exact `abort_candidate` receipt + candidate not-found + previous healthy + previous route |
| 正向 retire | 只接受 exact `retire_previous` receipt + candidate healthy/selected + previous exited/dead |
| 状态拒绝 | 缺失、started、indeterminate、failed/unavailable/unsupported result 均拒绝 |
| Scope | provider/project/environment/operation_id/action 任一不匹配均拒绝 |
| Digest | 重新计算的 request digest 不匹配、缺失或格式错误均拒绝 |
| 时间 | naive、future、stale、started 晚于 completed、completed 晚于 snapshot start 均拒绝 |
| 存储 | sidecar 不存在/损坏/无法只读打开均拒绝，且不得自动初始化或修复 |
| 崩溃窗口 | 方法调用前/执行中/返回前 crash 留下 started 或 indeterminate，不能产生 completion evidence；方法返回且 receipt durable 后，即使 journal 尚未推进，也只有在所有独立后置条件通过时才可形成 snapshot |
| 无副作用 | inspector/snapshot 路径不调用 Docker mutation，不执行 stop、start、remove、HAProxy set、journal update、active-pointer update 或 reservation release |
| 平台 | Linux 与 Windows CI 均验证 SQLite read-only 和 sidecar 路径行为 |

## 7. 明确不在本设计范围内

本设计不实现或暗示以下能力：

- 不执行 abort、retire、rollback、retry 或任何 deployment mutation；
- 不改 selector、active deployment pointer、journal phase 或 Host Router registry；
- 不释放 `needs_reconciliation` 的 scope reservation；
- 不签发或消费 reconciliation approval，不绕过双人审批；
- 不提供真实 IdP/HostAuthenticator；
- 不为云 Provider、异步 Provider 或其他 adapter 提供 Host synchronous completion 兜底；
- 不把本机 Host receipt sidecar描述成 provider-owned durable operation API。

**下一实施节点**为 T21.6.3.5.23：实现独立 Host synchronous completion contract/inspector、source binding、evidence 类型与 Host 只读组合接线；先通过 fake-store/fake-inspector 的完整拒绝矩阵，再由 Linux/Windows CI 验收。只有该节点通过后，才评估是否进行 disposable Docker Engine 的正向 reconciliation evidence 验收。真实 IdP、双人审批和任何 reconciliation mutation 仍保持关闭。


## Implementation and acceptance status (2026-11-20)

The implementation in `runtime/deployment_reconciliation_completion.py` defines a distinct `HostSynchronousOperationCompletion` and read-only Local Docker receipt inspector. The decision-specific collector accepts exactly one of a provider-native inspector or a Host synchronous completion inspector. The evidence contract keeps the source kinds distinct, and proposal validation accepts either complete evidence set without allowing a mixed set. The Local Docker Host builder reads the existing receipt sidecar in read-only mode and passes the snapshot read-start timestamp as a fence. The provider-native `LocalDockerProvider.inspect_operation()` implementation remains unchanged and returns `unsupported`.

The Local Docker source authenticator treats the receipt store as a local Host source, while runtime and route sources require the exact Host-pinned Docker daemon identity on each read. The authenticator accepts both alphanumeric Docker daemon IDs and canonical UUID-form IDs; Host pin comparison remains exact and case-sensitive. This does not claim remote or cryptographic protection against a Host administrator.

**Real Docker positive-snapshot acceptance completed:** CI [44734988946](https://github.com/rexyll/AI-Team/actions/runs/44734988946) passed the disposable Docker Engine Host job and uploaded artifact `router-host-synchronous-completion-snapshot-evidence` (ID `14628606633`). The JSON reports `fault_injection_verified`; the completion action is `retire_previous` with `result_status=succeeded` from `docker-local-host-call-receipts`; its `completed_at` precedes `snapshot_started_at`; all four evidence kinds are present; the candidate is healthy and is the effective Router target; the previous immutable runtime is exited; the journal remains `needs_reconciliation` with its revision fence; and `automatic_reconciliation_executed=false`. The smoke's own containers, Router, network and images were removed after verification.

This proves a disposable Docker Engine **read-only diagnostic snapshot**, not production identity validation or authorization. Production daemon pin provisioning, OS socket ACL/TLS, a real IdP-backed `HostAuthenticator`, KMS/SecretStore grant custody and an external trusted audit-head anchor remain separate production gates. No reconciliation mutation, rollback, selector/pointer/journal transition or reservation release is enabled.


### POSIX receipt-store filesystem checks

The Host receipt source authenticator additionally requires the sidecar to be owned by the current POSIX user, not readable/writable by group or other users, and located in a parent directory that is not group/other writable. Its endpoint identity digest includes the file and parent filesystem identity/ownership/mode. On Windows, this implementation does not inspect NTFS ACLs; the deployment service account and filesystem ACL remain part of the Host trust boundary. This is still not protection against a privileged Host administrator.
