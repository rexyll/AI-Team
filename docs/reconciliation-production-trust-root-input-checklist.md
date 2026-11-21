# 生产 Reconciliation 信任根部署输入清单

> 状态：供应商中立的部署输入与验收清单；不是部署配置，也不构成生产启用批准。  
> 适用范围：AI-Team Local Docker reconciliation approval trust roots。  
> 安全要求：本文件及 Git 仓库只记录非秘密的产品选择、资源标识和验收引用；不得写入密码、私钥、令牌、客户端密钥、KMS key material、证书私钥或可重放的认证证明。

## 1. 目的与启用边界

仓库已提供 Host 侧契约、双人审批 authority、加密 grant vault 接口、外部 audit-head CAS wrapper，以及只读 Host snapshot reader。Fake IdP/protector/anchor 只能验证接口与拒绝语义，不能证明部署环境真实身份、加密密钥或远端审计保留能力。

本清单将生产集成前需要部署负责人明确的输入和验收证据集中管理。它不选择 AWS、Azure、GCP、Keycloak、Entra ID、Okta、数据库或任何其他供应商；不 provision 远端资源；不引入默认值；不启用审批、消费或 deployment mutation。

在全部必需信任根经过独立验收前：

- 不得把测试 fake 或开发身份用于生产 authority。
- 不得向生产调用方暴露可签发/消费生产 reconciliation approval 的入口。
- 不得执行 rollback、abort、retire、retry 或其他 reconciliation mutation。
- 不得更改 Router selector、active pointer、journal phase、reservation 或 runtime lifecycle。
- 不得将本机 Host receipt、POSIX 文件权限或 SQLite 测试 fixture 描述为远端不可篡改审计或跨主机事务。

## 2. 部署负责人必须先给出的非秘密输入

请在受控部署记录中逐项填写；仓库只保留经过审查的非秘密配置引用，不要求把内部端点或租户细节提交到公开仓库。

| 输入域 | 必需选择/标识 | 必须明确的边界 |
|---|---|---|
| 部署范围 | project、environment、provider 标识及责任团队 | 标识必须与 journal、Host 和审批 scope 精确一致 |
| Host 拓扑 | 单 Host 或多 Host；Host OS；authority 实例数量；故障切换方式 | 当前本地文件锁只支持同一 Host 的进程协调；多 Host 不能共享独立本地 ledger 后假定安全 |
| 身份提供方（IdP） | 实际产品/协议、tenant/realm、issuer 标识、预期 audience、工作负载/客户端身份 | 明确谁可申请、谁可批准，以及两者如何证明为不同真实主体 |
| 身份验证策略 | 支持的认证方法、可信签发者/密钥来源、挑战与验证流程 | 明确 nonce/replay 防护、purpose、operation scope、expiry、撤销及密钥轮换 |
| KMS/SecretStore | 实际服务、密钥资源的非秘密标识、Host workload identity | 明确 AEAD/信封加密策略、AAD 绑定、授权策略、轮换、备份和恢复 |
| 外部 Audit Anchor | 服务类型、不可变 ledger namespace/ledger_id、远端资源标识 | 明确耐久、线性化 CAS、强一致 head 读取、远端保留和管理员分权 |
| Host/Docker trust | Docker endpoint 类型、预期完整 daemon ID、Host 身份/凭据来源 | 明确本地 socket ACL 或 Docker TLS；daemon pin 必须独立于运行时响应 provision |
| Router/HAProxy read sources | Router immutable identity、HAProxy read-only endpoint/权限、source IDs | 只允许精确身份绑定的只读读取；不授予 Runtime API 写权限 |
| Receipt/audit/grant 文件 | Host 服务账户、数据目录、文件系统/ACL 策略 | POSIX 检查已有实现；Windows NTFS ACL 当前仍须由部署侧强制并验收 |
| 运维责任 | IdP、KMS、Anchor、Docker Host、审批服务各自 owner 与 on-call | 明确故障冻结、密钥轮换、审计恢复、证据保留和双人复核责任 |

不要在此表中填入 secret value。Issuer、audience、tenant、key reference、ledger_id 和 daemon ID 等非秘密标识也应依据组织的信息分级规则保存在部署配置库；如不适宜公开，TaskPlan 只记录配置项已 provision 及其审查记录编号。

## 3. 各信任根的验收证据

### 3.1 IdP / HostAuthenticator

真实 adapter 必须验证并绑定可信 issuer、签名/credential、明确 audience、主体身份、nonce/replay、认证方法、purpose、operation 与 project/environment scope、挑战和授权 expiry。请求者与批准者必须是两个不同且可独立验证的主体；不能只比较用户自报名称。

至少提供以下 staging 证据：

- 合法身份/认证方法通过；错误 issuer、签名、audience、tenant 或主体映射拒绝。
- 重放 nonce、过期挑战、撤销主体、错误 purpose、错误 operation/scope 全部拒绝。
- requester 与 approver 相同主体、同一底层身份的别名/重复凭证不能通过双人独立性检查。
- IdP 不可用、密钥轮换期间无法验证或响应格式异常时 fail-closed；日志不包含令牌和原始证明。

### 3.2 KMS / SecretStore grant protector

真实 protector 必须使用外部管理密钥进行 authenticated encryption；AAD 必须覆盖仓库定义的 purpose/schema、approval ID、operation ID、provider/project/environment、expiry、proposal digest 和 evidence digest。不得使用软件密钥或明文回退。

至少提供以下 staging 证据：

- envelope save → Host restart → restore 成功；密文篡改、错误 AAD、错误 scope、reference 替换均拒绝。
- 未授权 workload identity、密钥服务不可用、密钥禁用/撤销时拒绝签发/恢复。
- 轮换后新 grant 使用新密钥，仍在保留窗口内的旧 grant 按策略可恢复；备份/灾备恢复已验证。
- 删除、保留和过期语义符合 grant-vault runbook；任何 ambiguous audit append 不提前删除 envelope。

### 3.3 外部 Audit Anchor

真实 adapter 必须将 checkpoint 存储于 Host audit ledger 目录之外，绑定 immutable ledger_id，并提供耐久、线性化的 compare-and-set。首条 audit event 之前由受控 provisioning 初始化 sequence=0、digest=全零值的 genesis；应用不得自行初始化、重置或 re-anchor。

至少提供以下 staging 证据：

- 新客户端实例能读取持久 checkpoint；旧 expected head 的 stale CAS 失败；并发 CAS 仅一个竞争者成功。
- CAS 成功但客户端丢失确认时，重读 head 能准确判定结果；服务不可用或结果不确定时，wrapper fail-closed。
- 本地 ledger 篡改、截断、local-ahead、local-behind、fork、错误 ledger_id 和运行期 namespace 漂移均阻断读写。
- 远端保留、备份、恢复、管理员分权与告警策略有独立审查记录。

不要把单机 SQLite 测试 fake 当作生产 Anchor；不要使用自动复制 local head 的“修复”脚本。恢复必须遵循 `deployment-reconciliation-audit-anchor-recovery-runbook.md`。

### 3.4 Docker Host、Router 与本机存储

Host 必须通过独立受保护配置 pin 完整 Docker daemon ID；每次证据读取都核对 daemon identity。Daemon pin 是额外身份检查，不替代 Unix socket ACL 或 Docker TLS。Router immutable identity、HAProxy route read-back、Host receipt sidecar、journal revision 和 runtime immutable IDs 必须保持精确绑定。

至少提供以下 staging 证据：

- daemon pin 正确时只读诊断通过；错误 daemon、错误 endpoint、socket/TLS ACL 不足和身份漂移拒绝。
- Docker runtime/Router/HAProxy 返回 scope、immutable ID、backend endpoint 或 route 与 journal 不匹配时拒绝。
- Host receipt、audit 和 grant 文件的 owner、目录权限及 Windows NTFS ACL 均由实际运行账户验证；不能以 POSIX 测试替代 Windows ACL 验收。
- 只读读取失败不会自动创建/adopt Router scope、创建数据库、修改 journal 或触发 Docker/HAProxy 写操作。

## 4. 单 Host / 多 Host 是先决架构决策

**单 Host**：必须证明审批 authority、local audit ledger、grant vault、receipt store 和 Docker Host 的受控放置关系；由一个受保护 Host 文件系统边界承载现有 OS-level coordination lock。备份/恢复时须保留 audit ledger 与外部 checkpoint 的一致性。

**多 Host**：当前实现不支持多个独立 local ledger 或仅靠共享目录/文件锁形成分布式事务。启用前必须另行实现并验收共享事务 audit append、全局 approval ID 唯一性、原子 one-use claim、集中或等价双人审批协调，并保留独立外部 trusted checkpoint。若该架构没有完成，必须保持 NO-GO，不得通过 sticky session、共享文件系统或增加重试次数来规避。

## 5. 分阶段 Go/No-Go

| 阶段 | 通过条件 | 未通过时 |
|---|---|---|
| G0 输入确认 | 第 2 节所有选择、scope、拓扑和 owner 明确；不含秘密 | 停留在 provider-neutral 契约，不写 provider-specific 代码 |
| G1 Adapter conformance | 每个真实 adapter 通过其正向、错误输入、超时、重放/并发、恢复和身份漂移测试 | 对应 adapter 不得注入生产 Host |
| G2 Staging trust-root proof | 使用真实 staging IdP/KMS/Anchor/Docker endpoint 完成第 3 节证据；独立审查权限与运维控制 | 保持 production authority 不可用 |
| G3 Read-only dual-approval dry-run | 真实身份双人认证；只读 snapshot/proposal/audit 验证；无生产 deployment mutation；审计链和远端 head 一致 | 关闭入口并保留证据；不得自动修复或继续 |
| G4 独立变更授权 | 另行完成 mutation executor 的威胁建模、接口设计、审批、故障注入和回滚安全评审 | 本清单不授权进入执行阶段 |

G0–G3 的通过不自动批准 G4。任何启用决定必须由部署负责人和安全负责人基于证据单独签署，且代码侧继续 fail-closed。

## 6. 部署输入记录模板（只填写非秘密信息）

- Deployment/project/environment:
- Host topology: single-host / multi-host (choose one)
- Host OS and service identity reference:
- IdP product/protocol and issuer reference:
- Expected audience and authentication-method policy reference:
- Requester/approver identity separation policy reference:
- KMS/SecretStore product and key-resource reference:
- Workload identity reference:
- External Audit Anchor product and immutable ledger_id reference:
- Anchor genesis provisioning/change record:
- Docker endpoint mode: local socket / authenticated TLS:
- Expected Docker daemon ID reference:
- Router/HAProxy read-source identity references:
- Receipt/audit/grant storage ACL review reference:
- Component owners and incident contacts:
- Staging conformance evidence locations:
- Security review / approval record:

**禁止填写**：password、access token、client secret、private key、certificate private key、KMS key material、bearer grant、一次性认证 proof 或其他可重放凭据。

## 7. 当前仓库状态与下一步

当前仓库提供的是 provider-neutral contracts 和测试夹具；真实 IdP、KMS/SecretStore、外部 Anchor、生产 Docker transport/ACL 和部署拓扑尚未由部署负责人指定或 provision。当前 safe next step 是完成 G0 输入确认，再按实际选择实现 adapter；不得自行推断或代替部署方选择供应商。

参考：
- [Host adapter contract](deployment-reconciliation-host-adapter-contract.md)
- [Protected grant custody](deployment-reconciliation-grant-vault.md)
- [External audit-head anchoring](deployment-reconciliation-external-audit-anchor.md)
- [Audit-anchor recovery runbook](deployment-reconciliation-audit-anchor-recovery-runbook.md)
