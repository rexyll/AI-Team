# AI-Team 全流程自动化任务计划（TaskPlan）

> 生成日期：2026-11-02　基线：`main` 分支（工作区干净）
> 目标：给出一个需求，AI 开发团队自主完成「需求分析 → 架构设计 → 输出文档 → 分配 Developer 开发 → 单元测试 → 集成联调 → 打包 → 提交测试团队测试 → 回归 → 输出测试报告 → 发布」全流程自动化。
> 方法：对照 `docs/team_completeness_audit.md`（研发团队完整性审计，2052 passed 基线）、`docs/phase19_architecture_plan.md`、`docs/release_readiness.md` 与 OpenClaw 工作流设计（Gateway 控制面、三级审批门、heartbeat/cron、memory/skills），逐环节核实仓库代码后制定。

## 一、现状梳理结论

### 1.1 用户目标管线 vs 当前实现

| # | 目标环节 | 当前实现 | 判定 |
|---|----------|----------|------|
| 1 | 给出需求 | CLI `main.py`（`--interactive`/`--clarifications`/`--analyze-only`/`--resume-session`） | ✅ |
| 2 | AI 自主分析需求 | Analyst 角色 + 质量自检重试 + 澄清协议（REQ 编号/优先级/验收标准/【假设】/【待确认问题】） | ✅ |
| 3 | 设计架构 | Architect 角色任务（含守卫/验收门禁） | ✅ |
| 4 | 输出文档 | DocWriter 五件套 + `acceptance_report.md`（确定性 REQ 追溯矩阵）+ `DELIVERY_MANIFEST.md`（sha256） | ✅（但仅在交付末尾一次性产出，见 1.2-❸） |
| 5 | 分配 Developer 开发 | Developer 池 + DependencyScheduler + ResourceGovernor + 多进程隔离 | ✅ |
| 6 | 单元测试 | Developer 工具循环内编写并运行测试 + Tester 证据审查（TEST_PASSED/FAILED）+ Reviewer 门禁（fallback/recovery） | ✅ |
| 7 | **集成联调** | 无产品级集成验证阶段。跨任务仅靠依赖上下文传递 + 各任务自测 | ❌ **断点** |
| 8 | 打包 | `runtime/packaging.py`（确定性 zip + 成员校验）+ `runtime/deployment.py`（installers + Dockerfile 模板 + 冒烟） | ✅ |
| 9 | 提交测试团队测试 | Tester 逐任务审查 LLM 证据；无独立 QA/对抗测试；无产品级系统测试阶段 | ⚠️ |
| 10 | **回归** | 无产品级全量回归阶段。打包冒烟会跑一次交付物测试套件，但不作为门禁、结果不回流测试报告 | ❌ **断点** |
| 11 | 输出测试报告 | `test_report.md`（DocWriter，数据源仅任务级证据） | ⚠️（缺集成/回归证据，见 1.2-❸） |
| 12 | **发布** | 部署包已生成，但无版本号、无 RELEASE_NOTES、无交付物 git 锚点（`HostGitOperationService` 已实现但交付阶段未使用）、无发布审批门、无回滚包管理 | ⚠️ **半断点** |

### 1.2 缺口清单（按对目标管线的影响排序）

- **❶ 集成联调阶段缺失**：所有产品任务完成后、打包前，缺一个「以交付物为整体」的集成验证（全量测试套件 + 跨模块冒烟），以及失败后的修复回流闭环。
- **❷ 回归阶段缺失**：同上——集成验证应承担产品级全量回归职责并输出证据；失败必须回流（修复任务 → 重执行 → 再回归），轮次有上限。
- **❸ 测试报告证据链不完整**：DocWriter 在打包冒烟之前运行，`test_report.md` 看不到集成/回归/静态门禁结果。
- **❹ 发布环节不完整**：无 semver 版本号、无 `RELEASE_NOTES.md`、交付物不入 git（可追溯/可回滚无从谈起）、发布无审批门（参考 OpenClaw 三级审批：自动执行 / 暂停 / 人工签核）。
- **❺ 质量独立性不足**（完整性审计已列）：静态门禁（ruff/mypy 在工具白名单但未强制）、无独立 QA 对抗测试角色、无依赖漏洞扫描。
- **❻ 项目管理缺口**：需求变更回流（变更→影响分析→增量任务图）、版本规划/里程碑、成本报告（`ModelUsageLedger` 台账已存在但不输出）、跨项目知识库。
- **❼ 角色缺口**：QA 工程师、安全工程师、发布/SRE、Release 管理、UI/UX、专项 Developer（按项目类型启用）。

### 1.3 现有部分需要优化的问题

| # | 问题 | 位置 | 处理 |
|---|------|------|------|
| O1 | `runtime/task_manager.py.bak` 备份文件混入源码目录 | runtime/ | 删除（T0） |
| O2 | `integration/test_real_team.py` 为遗留演示脚本，内容 GBK 乱码且不被 pytest 收集（`testpaths=tests`） | integration/ | 移除或重写为有效集成示例（T0） |
| O3 | `DevPlan.md` 停留在 Phase 18 + 交付能力升级（2026-09-13），而仓库已推进 Phase 19 多个 slice 与完整性审计，计划文档与实际脱节 | DevPlan.md、docs/phase19* | 在 DevPlan 追加 Phase 19/20 记录并指向本 TaskPlan（T4） |
| O4 | `docs/visio/` 未纳管（untracked） | docs/visio/ | 纳入版本控制或 .gitignore（T0） |
| O5 | `CHANGELOG.md` 停在 v0.9.1；交付物无版本管理闭环 | CHANGELOG.md | 随 T3 发布阶段一并补齐机制 |
| O6 | 打包冒烟结果（SMOKE_REPORT）不作为交付门禁，也不回流测试报告 | runtime/deployment.py | 随 T1/T2 一并修正语义（集成门禁前置，冒烟保留为部署层验证） |

### 1.4 OpenClaw 工作流设计的借鉴点

详细调研见 `_research/D_openclaw_patterns.md`（12 个官方文档页 + 6 个官方 issue + 3 个二手来源，全部带 URL）。经核实的十条可迁移模式：

1. **分层审批门 + 身份绑定 + fail-closed**（工具面→提权门→exec approvals→沙箱四层正交；审批五档 deny/allowlist/ask/auto/full；白名单绑定可执行文件 real-path + argv sha256；UI 不可达时 askFallback 默认 deny）→ T3 发布审批门直接采用「默认暂停等确认、显式越过才放行」语义。
2. **计划-执行-复核分离**（sub-agent announce 机制）→ 已有 Planner/Developer/Tester/Reviewer 分离对齐；T6 QA 角色进一步强化「执行者≠验证者」。
3. **会话可恢复**（writer-claim 写者围栏 + 终态重放）→ 已有 checkpoint/persistence/recovery 对齐，无需新增。
4. **心跳自检**（持久化显式 job + 安静时段）→ P3 交付后监控/缺陷回流借鉴。
5. **技能包**（SKILL.md + 不可变版本 + 安装门）→ P3 跨项目知识库 / Plugin 生态借鉴。
6. **记忆分层 + 门控晋升 + 人审** → P3 知识库沉淀策略借鉴。
7. **声明式路由 + 死信队列** → 失败任务的兜底归宿（P2/P3 参考）。
8. **控制面/执行面分离** → 已有 AgentRouter/TaskWorkflow 边界对齐，保持「不引入第二运行时」。
9. **失败如实上报（禁止伪造完成态）** → T1 集成回归轮次耗尽必须如实判 FAILED，禁止静默放行。
10. **metadata-only 审计台账**（不落敏感原文）→ 已有 secret 脱敏/围栏对齐；新增阶段事件遵循同规则。

OpenClaw 官方 issue 也佐证了审批门的三个坑（子进程需显式继承审批、审批需阻塞语义、配置漂移会回退权限）——T3 实现时规避。

## 二、任务节点

> 工作规则（沿用仓库既有纪律）：每个节点 = 仓库现状评审 → 最小契约保持改动 → 聚焦测试 → 全量回归（`pytest -q`）→ 本文件勾选记录。安全边界（沙箱/权限/出口/围栏/脱敏）不得绕过。

### P0 全流程断点补齐（本轮核心）

- [x] **T0 仓库卫生**（2026-11-02 完成，提交 60e2610）
  - 删除 `runtime/task_manager.py.bak`；处理 `docs/visio/` 未纳管；移除/重写 `integration/test_real_team.py` 乱码遗留。
  - 验收：`git status` 干净、全量回归绿。
- [x] **T1 集成联调与回归验证阶段（Integration & Regression Phase）**（2026-11-02 实现：runtime/integration_verification.py + ProjectOrchestrator 接线 + REWORK 回流轮；验收：tests/test_integration_verification.py 8 passed + tests/test_integration_phase_orchestrator.py 6 passed + 交付/打包/文档既有契约 32 passed）
  - 新增 `runtime/integration_verification.py`：确定性执行交付物全量测试套件（复用/抽取 `run_smoke_verification` 的隔离副本机制），产出结构化证据（通过率、失败明细、命令、耗时）。
  - 失败回流：构建 rework 任务（developer 角色 + 失败证据上下文）注入任务图（复用 `TaskManager.replace_task_graph` / recovery_replan 机制），重执行后再回归，轮次上限可配（默认 2），超限判 FAILED 并如实上报。
  - 接线：`ProjectOrchestrator._run_delivery_phase` 中 DocWriter **之前**执行（先集成回归、后写报告、再打包）；事件 `project.integration_started/completed/failed`。
  - 验收：mock 全链路覆盖三种路径（一次通过 / 修复后通过 / 轮次耗尽失败）；聚焦测试 + 全量回归绿。
- [x] **T2 测试报告证据链增强**（2026-11-02 完成：DocWriter context 新增 integration_evidence，test_report.md 撰写要求新增『集成联调与全量回归』章节；证据传递由 tests/test_integration_phase_orchestrator.py::test_integration_passes_first_round_and_evidence_reaches_docs 契约覆盖）
  - DocWriter context 增加集成/回归证据块；`test_report.md` 撰写要求增加「集成联调」「全量回归」章节（含命令与结果）。
  - 验收：契约测试验证证据传递与文档要求生效。
- [x] **T3 发布阶段（Release Phase）**（2026-11-02 实现：runtime/release.py + HostGitOperationService 新增 init/tag/is_repository/head_commit 语义 + ProjectOrchestrator 接线（release 在 manifest 之前、打包门禁之后）+ main.py --release/--release-version/--auto-release；验收：tests/test_release_phase.py 9 passed + tests/test_host_git.py 扩展契约 + 编排器级发布锚点测试；待全量回归确认）
  - 新增 `runtime/release.py`：semver 版本号（显式 `--release-version` 优先，缺省按交付历史递增）、`RELEASE_NOTES.md`（确定性拼接 REQ 清单/测试结论/验收判定）、交付物 git 锚点（扩展 `HostGitOperationService` 增加 `init`/`tag` 语义，host-owned）、发布记录 `release_log.json`。
  - 审批门（借鉴 OpenClaw 三级审批）：打包与验证自动执行；**发布提交默认暂停等待确认**，`--auto-release` 显式越过；CLI 透传 `--release`/`--release-version`/`--auto-release`。
  - 验收：单测覆盖版本号规则、notes 生成、git 锚点、审批门两条路径；全量回归绿。
- [x] **T4 文档与计划同步**（2026-11-02 完成：DevPlan 追加 Phase 20 记录、README 状态/CLI/架构更新、CHANGELOG 补录、文档索引指向 TaskPlan.md）
  - DevPlan 追加 Phase 20 记录（指向本 TaskPlan）；README/`docs/AI-Team-项目文档索引.md` 更新管线全景（含集成/回归/发布阶段）；`CHANGELOG.md` 补录本阶段变更。
  - 验收：文档契约测试（`test_documentation_setup_contract.py` 等）保持绿。

### P1 质量独立性（完整性审计建议 1/3/5）

- [x] **T5 静态质量门禁**（2026-11-02 完成，提交 e20022a：ruff 强制（钉死 E9/F63/F7/F82 破坏性规则集，不含风格项；--no-cache），mypy 默认关闭（AI_TEAM_STATIC_MYPY=1 开启，默认记录、AI_TEAM_STATIC_MYPY_ENFORCE=1 强制）；静态失败与套件失败共用同一修复回流；全量回归 2093 passed）
- [x] **T6 QA 对抗测试角色**（2026-11-02 完成，提交见执行记录：agents/qa.py 自有有界工具循环（BaseAgent 能力过滤 + ToolInvocationService role=qa）；qa 角色 = READ+EXECUTE（无 WRITE，产品文件不可经工具边界修改）；产品级 QA 阶段在集成通过后、文档前执行一次；QA_FAILED 如实上报并门禁发布（不阻断打包）；QA 证据入测试报告与发布说明）
- [x] **T7 依赖漏洞扫描**（2026-11-02 完成，提交见执行记录：runtime/dependency_scan.py 离线 SBOM——requirements 钉死核查 + 源码第三方导入未声明检测；漏洞库查询按出口策略如实记 unavailable，不静默执行 pip-audit；记录性证据入测试报告，不做门禁）

### P2 项目管理（完整性审计建议 4/5）

- [x] **T8 成本报告**（2026-11-02 完成，提交见执行记录：ModelUsageLedger 接入真实 ProviderLLM 工厂路径（per-run ledger + run-scoped project key）；用量汇总进 delivery 记录、交付文档『模型用量与成本』章节与发布说明；费率未配置时如实标注未估算成本）
- [x] **T9 需求变更回流**（2026-11-02 完成，提交见执行记录：--change-request 文件 → Analyst 权威修订通道（customer.change_request 围栏 + CHG-xxx 受理规则）→ 修订后规格重规划为全新任务图；analyze-only 同样支持；残留：持久化项目的增量续跑（只重跑受影响任务）已由 T14 关闭）
- [x] **T10 版本规划/里程碑**（2026-11-03 完成：`runtime/release_plan.py` 里程碑计划解析 + 共享 plan 文档 + 跨交付物 release_log 汇总；`--requirements-file` 串行逐需求完整交付且各自版本号、失败即停并如实标记 skipped、共享 plan 必写；`--milestone` 里程碑标签入发布说明与 release_log；`--release-history [PATH]` 只读版本汇总视图（text/json）；验收：test_release_plan.py 20 passed + 全量 2138 passed）：设计要点——基于 T3 的 per-delivery semver 与 release_log.json，增加多需求批量入口（如 --requirements-file，逐个需求串行交付、各自版本号、共享发布计划）；多项目并行可评估 multi_project_scheduler 复用（本轮采用确定性串行，并行留待后续评估）；交付物版本列表汇总视图（跨 release_log 聚合）

### P3 组织记忆与交付后（完整性审计建议 6/7，OpenClaw heartbeat/memory 借鉴）

- [x] **T11 跨项目知识库**（2026-11-03 完成：`runtime/knowledge_base.py` 确定性提取 模式/坑/规范（验收缺口与警告、集成失败或返工、静态门禁失败、QA_FAILED、依赖声明问题、发布锚点；绿色交付生成基线模式）；条目 id 哈希（项目+类型+标题）保证重复提取幂等；单文件原子存储 + 进程锁，损坏即 fail-closed；按 类型/标签/角色/关键词 过滤加载（坑优先、新者优先、有界）；分析提示词与 DocWriter 上下文以不可信围栏注入并声明历史不得覆盖客户当前需求；交付后自动回流知识资产；CLI `--knowledge-base/--knowledge-query/--knowledge-list/--knowledge-extract`；验收：tests/test_knowledge_base.py 10 passed）
  - 历史交付模式/坑/规范沉淀为可加载资产。
- [x] **T12 UI/UX 与专项开发角色**（2026-11-03 完成：`runtime/project_type.py` 纯关键词确定性项目剖面（web/desktop/mobile/API/data/CLI/library/general，需求文本权重 2、分析/计划权重 1，记录命中信号），剖面决定启用角色；`agents/ui_ux.py` 零工具设计角色（信息架构/布局/交互状态/设计令牌/响应式/WCAG/可用性验收标准），仅当剖面需要界面且运行时已注册该角色时，确定性注入 `UX-001`（依赖架构任务）并让界面相关 Developer 任务依赖它，否则计划不变（模型误产的 ui_ux 降级为 architect 以保证可执行）；Developer 按任务文本匹配剖面启用的专项技能（frontend/backend/data/desktop/mobile/CLI），专用提示词注入，未命中保持通用；UI/UX 规范进入 DocWriter 上下文与设计文档要求；验收：tests/test_specialist_roles.py 18 passed + 全量 2166 passed）
  - 按项目类型启用，而非所有项目都跑设计/专项角色；不改计划 schema 与工作流图。
- [x] **T13 交付后监控/缺陷回流**（2026-11-04 完成：`runtime/monitoring.py` 在发布后、清单前写入 `monitoring/health_contract.json` + `MONITORING.md`，契约只声明可离线验证的探针（发布锚点/清单完整性/回归套件），并如实标注未接入云 APM；`python main.py --monitor-check PATH` 心跳自检，写入 `monitoring/status.json`，healthy/degraded/failed 三态且非 healthy 退出码 1；`runtime/defect_reflow.py` 解析确定性缺陷清单（`## 缺陷 DEF-001 标题` + 严重级别/描述/影响版本/复现步骤，严格校验重复编号、未知字段、非法严重级别与不在发布历史中的版本），生成 `hotfix_request.md`（CHG-xxx，可复用变更通道）与 `docs/defect_report.md`（缺陷→热修任务→版本映射）；`core/hotfix_runner.py` + CLI `--hotfix-project/--defect-intake/--hotfix-version` 直接复用既有执行管线（集成回归/QA/补丁发布/清单/重新打包），结果 fixed/pending/failed 如实入报告；验收：tests/test_defect_reflow.py + tests/test_monitoring.py + 编排器契约 38 passed）
  - 监控无外部部署环境时以交付物自检契约落地，不伪造云监控接入；缺陷回流要求已有发布基线，失败不静默放行。
- [x] **T14 持久化项目增量续跑**（2026-11-04 完成：`runtime/change_impact.py` 确定性变更影响分析——旧任务图与新任务图按“计划 id → 归一化标题”保守匹配；仅当标题、描述与（id 映射后的）依赖集合全部不变才复用已完成状态/结果/测试证据，变更任务及其下游传递性重置为待执行，无法匹配的新任务一律视为新增工作；被变更删除的任务从任务图移除并在报告中如实列出，不复用其证据；`ProjectOrchestrator.revise_persisted` 串起“变更请求 → Analyst 权威修订 → 重规划 → 增量任务图 → 只执行受影响任务 → 集成回归/QA/文档/打包门禁 → 原子写回快照”，期间按边界检查点持久化；CLI `--revise-project PATH --change-request PATH`（配合原始需求文本，复用同一 workspace 锚定；JSON 输出附 `revision` 报告）；无法判定时如实退化为全量重跑并标注 `mode=full`；验收：tests/test_incremental_revision.py 19 passed）
  - 增量判定不依赖 LLM、可离线验证；未受影响任务的完成证据与工具执行历史保留，失败任务如实上报。

### P4 团队完整性与标准流程对齐（2026-11-04 团队完整性复审）

- [x] **T15 安全工程师角色 + 交付前安全门禁**（`agents/governance.py` role=`security` 零工具面；`runtime/security_audit.py` 确定性离线扫描——私钥/云与供应商令牌/危险构造（shell=True、verify=False、pickle.loads、yaml.load、eval/exec）+ 依赖声明参考证据；高危即 `SEC_FAILED`；报告 `docs/security_audit.md` 证据脱敏，不写回原始密钥；编排器在 QA 后、文档前执行，安全证据进入 DocWriter/测试报告上下文；确定性 `SEC_FAILED` 不可被 Agent 复核改写为 `SEC_PASSED`）
- [x] **T16 发布/运维工程师（SRE）角色 + 部署就绪审查**（`agents/governance.py` role=`sre` 零工具面；`runtime/deployment_readiness.py` 检查部署指引（安装/启动/回退）、监控契约 `monitoring/health_contract.json` + `MONITORING.md`、交接文档集、发布后的 `RELEASE_NOTES.md` 版本记录；`SRE_READY`/`SRE_DEGRADED`；报告 `docs/sre_readiness.md` 随交付清单校验；外部云部署/APM 接入为显式边界，不伪造）
- [x] **T17 发布经理角色 + 发布 GO/NO-GO 门禁**（`agents/governance.py` role=`release_manager` 零工具面；`runtime/release_gate.py` 确定性阻断 integration_failed/qa_failed/security_failed，发布经理可追加 `RELEASE_NO_GO` 但不可豁免确定性阻断；编排器在发布阶段前执行，阻断时记录 `project.release_blocked` 且不执行发布；三角色统一注册于 `config/model.py`/`runtime/agent_factory.py`/`security/runtime_capability.py`）
  - 团队配置核对：标准研发团队角色（分析师/规划/架构/UI-UX/开发/测试/评审/QA/安全/SRE/发布管理/文档）已齐全；流程核对：需求澄清→设计→实现→测试→QA→安全→文档→验收→发布门禁→发布→监控→部署就绪→清单/打包，缺口已按标准 SDLC 补齐。

## 三、执行记录

| 日期 | 节点 | 结果 | 证据 |
|------|------|------|------|
| 2026-11-02 | 梳理 + TaskPlan 建立 | 完成（P0-P3 节点定义） | 本文件 |
| 2026-11-02 | T0 仓库卫生 | 完成 | 提交 `60e2610` |
| 2026-11-02 | T1 集成联调与回归阶段 + T2 测试报告证据链 | 完成；全量回归 2066 passed | 提交 `335fa01` |
| 2026-11-02 | T3 发布阶段（semver/notes/git 锚点/审批门） | 完成；全量回归 2084 passed | 提交 `2b7abcc` |
| 2026-11-02 | T4 文档与计划同步 | 完成；文档契约 + 全量回归绿 | 提交 `33e4880` |
| 2026-11-02 | T5 静态质量门禁 | 完成；全量回归 2093 passed | 提交 `e20022a` |
| 2026-11-02 | T6 QA 对抗测试角色 | 完成；全量回归 2101 passed + 安全回归 221 passed | 提交 `77589b0` |
| 2026-11-02 | T7 依赖漏洞扫描（离线 SBOM） | 完成；全量回归 2105 passed | 提交 `d889b20` |
| 2026-11-02 | T8 成本报告（用量归因→文档） | 完成；全量回归 2110 passed | 提交 `6fb76bd` |
| 2026-11-02 | T9 需求变更受理（CHG 修订→重规划） | 完成；全量回归 2118 passed | 提交 `0b6a9be` |
| 2026-11-03 | T10 版本规划/里程碑（批量计划/里程碑/版本汇总） | 完成；全量回归 2138 passed（venv Scripts 在 PATH 时；含 test_release_plan 20），裸调用 .venv\Scripts\python.exe 时 2 条 run_command 用例因 `python` 解析到 Windows 商店占位符失败（环境差异，非本次改动） | 本提交 |
| 2026-11-03 | T11 跨项目知识库（确定性沉淀/过滤加载/CLI/交付后回流） | 完成；聚焦 tests/test_knowledge_base.py 10 passed；全量回归 2148 passed | 本提交 |
| 2026-11-03 | T12 UI/UX 与专项开发角色（确定性项目剖面/按类型启用/设计任务注入/专项技能匹配） | 完成；聚焦 tests/test_specialist_roles.py 18 passed；全量回归 2166 passed；静态门禁 E9/F63/F7/F82 通过 | 本变更（工作区，待提交） |
| 2026-11-04 | T13 交付后监控/缺陷回流（健康契约+心跳自检/缺陷清单→热修任务→重新打包） | 完成；聚焦 tests/test_defect_reflow.py + tests/test_monitoring.py + 编排器契约 38 passed；静态门禁 E9/F63/F7/F82 通过；全量回归 2193 passed | 本变更（工作区，待提交） |
| 2026-11-04 | T14 持久化项目增量续跑（确定性影响分析/证据保留/只跑受影响任务/CLI 快照修订） | 完成；聚焦 tests/test_incremental_revision.py 19 passed；静态门禁 E9/F63/F7/F82 通过；全量回归 2212 passed | 本变更（工作区，待提交） |
| 2026-11-04 | P4 团队完整性与标准流程对齐（安全工程师/SRE/发布经理三角色 + 安全审计/发布门禁/部署就绪审查） | 完成；聚焦 tests/test_team_governance_roles.py 15 + tests/test_security_release_workflow.py 19 passed；静态门禁 E9/F63/F7/F82 通过；全量回归 2244 passed（同步更新配置契约角色清单） | 本变更（工作区，待提交） |


---

# Phase 21：通用项目端到端交付能力补强（2026-11-14）

> 基线：`main`；不合并历史分支，不创建新分支，按小步提交推进。
> 总目标：把当前已具备完整 Python 本地研发流程的 AI-Team，提升为具备可隔离并行开发、按技术栈真实构建/测试、可执行验收、可追溯 CI/PR 与可验证部署能力的工程交付系统。
> 执行原则：先修复当前 CI 基线，再逐项补齐运行时能力；每个节点先读现有契约与安全边界，再做最小改动；聚焦测试通过后才进入下一节点。任何无法真实执行的外部动作必须标记 unavailable/deferred，不得伪造成功。

## 21.1 当前基线复核

- `main` 是当前唯一集成基线；历史分支存在大量落后提交，不做整支合并。
- `docs/production_configuration.md` 明确 Python 3.14 为硬性要求（PEP 649）；CI 仍包含 Python 3.13，因此矩阵与项目支持声明不一致。
- `requirements.txt` 只有运行依赖，CI 安装后执行 `python -m pytest -q`，但未安装 pytest，导致测试阶段启动前即失败。
- 项目类型识别覆盖 web/desktop/mobile/API/data/CLI/library/general，但集成验证、测试发现和部署逻辑仍以 Python/pytest 为中心；识别类型不等于具备对应技术栈的完整构建与部署能力。
- Developer 并行执行使用共享项目工作区；尚未证明每个 Developer 的文件写入边界具备独立 workspace lease/隔离。
- 当前验收报告以需求编号和文档/测试报告证据为主，需补齐 REQ → 可执行验收测试 → 实际运行结果的强关联。
- Host Git 能力以本地仓库操作为主；远端 PR 生命周期、CI 状态回读与安全合并闭环仍需专门集成。
- 部署/监控现有能力主要是本地契约与离线自检；尚不等同于真实镜像发布、云环境部署、外部 APM 和自动回滚。

## 21.2 任务列表

### P0：修复可验证基线与并行写入安全

- [x] **T21.1 CI 基线修复**（2026-11-14 完成：requirements-dev.txt 安装 pytest/ruff/mypy；CI 仅运行 Python 3.14，注入仅供 mock 测试的 .invalid 假 Provider 配置；安全回归使用 always() 确保主回归失败时仍执行；修正注入式 ProviderLLM 测试模型参数、spawn Event 生命周期与并发审计顺序断言；最终全量回归 2236 passed / 9 skipped，安全回归 233 passed / 9 skipped，GitHub Actions run 43586159954 全绿）
  - 新增开发依赖清单（至少包含 pytest，采用兼容 Python 3.14 的受支持版本范围）。
  - CI 安装运行依赖与开发依赖；将 Python 矩阵调整为项目明确支持的 3.14，避免在不支持的 3.13 上制造误报。
  - 保持全量回归与安全回归两个阶段；不得因安装失败而跳过安全门禁。
  - 验收：GitHub Actions 全量回归与安全回归均启动并通过；同时验证本地标准安装指令。
- [ ] **T21.2 Developer Workspace 隔离**（第一阶段核心实现完成，整体仍未验收：任务级快照/ContextVar 沙箱/并发工具上下文传播；跨进程 OS 文件锁；原子租约元数据；死进程租约回收；同路径冲突 fail-closed；符号链接与路径边界检查；异常退出清理。尚余真实多 Developer 项目端到端验证，以及依赖环境适配策略）
  - 审查历史 `feature/reviewer-reliability-fallback` 中 workspace manager 的实现，只择取可证明安全的设计，不合并整支分支。
  - 实现说明：[`docs/developer_workspace_isolation.md`](docs/developer_workspace_isolation.md)，记录租约生命周期、跨进程锁、崩溃回收、依赖目录策略及当前安全边界。
  - 为并行 Developer 提供每任务/每执行者隔离工作区、租约/写者围栏、路径约束与结果回收机制。
  - 失败、超时、取消、进程崩溃时必须释放租约或可恢复；禁止两个执行者静默覆盖同一工作区。
  - 验收：并行写入互不污染、租约冲突 fail-closed、异常退出恢复、路径逃逸拒绝；全量回归通过。
  
阶段进展（2026-11-14）：
- 已完成 `runtime/developer_workspace.py` 的任务快照、SHA-256 冲突检测、同目录原子文件替换、OS 进程锁与租约 sidecar 元数据。
- `Orchestrator` 在 Developer 成功时合并，失败/异常时通过 `finally` 丢弃；ContextVar 使并发工具调用保留任务级沙箱。
- 新进程只回收无元数据的未完成目录或 owner PID 已确认退出的租约；活动租约保留，损坏元数据不自动删除。真实子进程 `os._exit` 故障测试通过。
- 依赖目录（`.venv`、`node_modules`）不共享、不合并；项目适配器需创建任务级环境或提供验证过的只读缓存。
- 已补充多文件 merge journal：先 staging/backup，再写 prepared/applying/committed 状态；进程在提交标记前崩溃时由新 manager 回滚整批文件，提交标记后只清理事务目录；损坏 journal/缺失 backup fail-closed。剩余：真实多 Developer 项目端到端和任务级依赖安装闭环。

### P1：真实多技术栈构建与可执行验收

- [ ] **T21.3 Project Adapter 架构**（第一阶段已实现：独立于项目类型的语言适配器注册表；Python 与 Node/npm detect/plan；install/build/test/package/smoke/deploy 的 supported/skipped/unsupported 状态；命令只经 ToolInvocationService 的 run_command 执行；run_command 增加 1–3600 秒超时参数。已接入 ProjectOrchestrator 集成门禁（默认关闭；`AI_TEAM_PROJECT_ADAPTERS=1` 启用；多技术栈用 `AI_TEAM_PROJECT_ADAPTER=python|node` 显式选择），失败会进入有界返工并写入交付证据。仍需真实 Windows 主机经默认 run_command 的 E2E、依赖缓存策略与 pnpm/yarn 支持/明确拒绝）
  - 新增统一适配器协议/注册表，至少定义 detect、install、build、test、package、smoke、deploy 能力及明确的 unsupported 状态。
  - 首批实现 Python 与 Node.js；项目类型与语言/框架检测分离，不能仅凭 web/API 分类就假定技术栈。
  - 所有命令经过现有权限策略/沙箱，具备 allowlist、超时、工作目录限制、输出脱敏；不允许 adapter 绕过 ToolInvocationService。
  - 设计说明：[`docs/project_adapter_architecture.md`](docs/project_adapter_architecture.md)。
  - 验收：Python 与 Node.js fixture 项目分别完成依赖安装（离线 fixture 可替代网络安装）、构建、测试、打包和冒烟；未知技术栈明确拒绝或降级。
- [ ] **T21.4 Executable Acceptance Evidence**
  - 建立 REQ → acceptance test ID → 命令/测试选择器 → 实际执行结果 → 日志/报告摘要的确定性证据模型。
  - 每条强制 REQ 必须关联至少一条可执行验收测试；缺失、未执行、失败均不能标记验收通过。
  - 保留人工 UAT 签核作为可选外部证据，不能由 Agent 伪造。
  - 验收：通过、失败、未执行、无关联测试、证据过期等路径均有契约测试；报告与发布门禁一致。
  
### P2：外部协作与部署闭环

- [ ] **T21.5 SCM / PR / CI Provider**
  - 定义 SCM provider 接口，首批支持 GitHub：分支/提交推送、PR 创建/更新、CI 状态读取、review 状态读取、合并前检查。
  - 远端写操作与合并必须受 host-owned 权限边界和显式审批控制；Agent 不得自行扩大 token 权限。
  - CI 失败反馈可转成修复任务，但需限制轮次并保留原始状态证据。
  - 验收：mock provider 全路径契约 + GitHub 最小集成验证；权限不足时 fail-closed。
- [ ] **T21.6 Deployment / Operations Adapters**
  - 把本地打包、容器构建、镜像扫描/发布、环境部署、健康探针、回滚拆成可替换 adapter。
  - 首批提供本地 Docker 构建/运行/健康检查；云厂商部署作为后续 provider，不宣称未接入的云能力。
  - 回滚必须基于明确的上一个健康版本和可验证的部署记录。
  - 验收：本地容器端到端 fixture；构建失败/健康检查失败/回滚失败均如实报告。
  
### P3：工程质量与真实项目验收

- [ ] **T21.7 供应链与质量门禁增强**
  - 增加覆盖率阈值、性能基准/预算与可选压力测试门禁。
  - 在明确网络出口白名单下接入漏洞数据库与许可证扫描；SBOM、依赖锁定、构建来源/制品摘要可追溯。
  - 验收：阈值阻断、工具不可用、网络拒绝、许可证冲突等场景均如实输出。
- [ ] **T21.8 Real Project E2E**
  - 选取 Python CLI/API 与 Node.js Web 两类代表项目，从自然语言需求启动完整交付。
  - 检查需求追溯、隔离开发、构建测试、可执行验收、QA/安全、打包、发布记录与交付说明。
  - 输出能力边界报告，明确哪些步骤由本地执行、哪些依赖用户凭证/环境/人工审批。

## 21.3 优先级与停止条件

1. 先完成 T21.1 并恢复可用 CI；CI 未绿，不进入后续大规模重构。
2. T21.2 与 T21.3 是通用交付能力的核心阻塞项，优先于增加 Agent 角色。
3. T21.4 是发布可信度门槛；没有可执行证据不得把文档追溯等同于功能验收。
4. T21.5/T21.6 需要外部凭证或真实环境时，先完成接口与 mock 契约；真实集成需凭证到位后再验证。
5. 每一节点独立提交到 `main`；不做历史分支整合，不批量重写无关模块。
6. 如果安全边界、现有测试契约或数据兼容性无法证明，暂停该节点并记录阻塞，不以弱化测试换取通过。

## 21.4 Phase 21 执行记录

| 日期 | 节点 | 结果 | 证据 |
|---|---|---|---|
| 2026-11-14 | 基线复核与 Phase 21 计划 | 已定义；待逐项执行 | 本文件 |
| 2026-11-14 | T21.1 CI 基线修复 | 完成；全量回归 2236 passed / 9 skipped；安全回归 233 passed / 9 skipped | [GitHub Actions #9](https://github.com/rexyll/AI-Team/actions/runs/43586159954)，提交 `518e3f3` 及前序 CI 修复提交 |
| 2026-11-14 | T21.2 Developer Workspace 隔离（第一阶段核心） | 核心实现与故障验证通过；全量回归 2255 passed / 9 skipped；安全回归 233 passed / 9 skipped。已实现跨进程锁、持久化租约、死进程回收、多文件事务回滚、损坏日志 fail-closed、冲突检测、路径/符号链接防护；整体 T21.2 仍待真实多 Developer E2E 与任务级依赖安装闭环 | [GitHub Actions run 43592173178](https://github.com/rexyll/AI-Team/actions/runs/43592173178)；提交 `c6f0063`、`735de79`、`f1f19a9`、`010ee89`、`c87820d`、`fbfa30e`、`419ddb1`、`469c944`、`e2d930f` 等 |
| 2026-11-14 | T21.3 Project Adapter 架构（第一阶段） | Python/Node npm adapter 注册表与动作计划完成；执行器通过 ToolInvocationService 调用 run_command，超时 1–3600 秒，命令结果无 exit_code 时 fail-closed；全量回归 2273 passed / 9 skipped，安全回归 233 passed / 9 skipped；Python 与 Node/npm fixture 已通过 ToolInvocationService 实际执行 install/build/test/package/smoke；ProjectOrchestrator 已接入 opt-in 适配器集成门禁、工作区作用域、失败返工证据与审计历史。编排层测试使用真实 ToolInvocationService + stub command；仍未完成 Windows 生产终端 E2E、依赖缓存策略与 pnpm/yarn 支持 | [GitHub Actions run 43598140624](https://github.com/rexyll/AI-Team/actions/runs/43598140624)；新增 `runtime/project_adapters.py`、`tests/test_project_adapters.py`、`docs/project_adapter_architecture.md` |
