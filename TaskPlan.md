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
| 2026-11-15 | T21.6.3 SQLite transaction repair CI #295 | 事务连接上下文恢复 `with connection` commit/rollback 语义并在 finally 显式关闭；#294 暴露的未提交写入问题在修复提交上通过全量回归、安全回归与 Windows smoke。 | [GitHub Actions #295](https://github.com/rexyll/AI-Team/actions/runs/43674984329)；提交 `23e0db7` |
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
- [x] **T21.2 Developer Workspace 隔离（v1 完成，2026-11-14）**：任务级快照/ContextVar 沙箱/并发工具上下文传播；跨进程 OS 文件锁；原子租约元数据与死进程回收；多文件事务回滚；冲突/路径/符号链接 fail-closed；异常退出清理；可选任务级依赖安装。`AI_TEAM_TASK_ENVIRONMENTS=1` 在 lease 内创建 Python `.venv` 或 Node `node_modules`；pip 缓存位于 lease 的 `.ai-team-cache/pip`，npm 缓存位于 `node_modules/.cache/npm`。依赖目录不复制、不合并、不进入交付清单/冒烟 staging；安装失败阻断 Developer workflow。新增两个并行 Developer 的真实 `DeveloperAgent` + 确定性 `MockLLM` 工具循环 E2E，覆盖独立 lease、真实 `write_file` 工具、并行源码合并与环境回收。边界：不复用跨任务缓存；真实 ProviderLLM/外部凭证 E2E 留待 T21.8。
  - 审查历史 `feature/reviewer-reliability-fallback` 中 workspace manager 的实现，只择取可证明安全的设计，不合并整支分支。
  - 实现说明：[`docs/developer_workspace_isolation.md`](docs/developer_workspace_isolation.md)，记录租约生命周期、跨进程锁、崩溃回收、依赖目录策略及当前安全边界。
  - 为并行 Developer 提供每任务/每执行者隔离工作区、租约/写者围栏、路径约束与结果回收机制。
  - 失败、超时、取消、进程崩溃时必须释放租约或可恢复；禁止两个执行者静默覆盖同一工作区。
  - 验收：并行写入互不污染、租约冲突 fail-closed、异常退出恢复、路径逃逸拒绝；全量回归通过。
  
阶段进展（2026-11-14）：
- 已完成 `runtime/developer_workspace.py` 的任务快照、SHA-256 冲突检测、同目录原子文件替换、OS 进程锁与租约 sidecar 元数据。
- `Orchestrator` 在 Developer 成功时合并，失败/异常时通过 `finally` 丢弃；ContextVar 使并发工具调用保留任务级沙箱。
- 新进程只回收无元数据的未完成目录或 owner PID 已确认退出的租约；活动租约保留，损坏元数据不自动删除。真实子进程 `os._exit` 故障测试通过。
- 依赖目录（`.venv`、`node_modules`、`.ai-team-cache`）按 lease 隔离，不复制、不合并；任务级环境 provisioner 已实现，跨任务只读缓存复用仍延期。
- 已补充多文件 merge journal：先 staging/backup，再写 prepared/applying/committed 状态；进程在提交标记前崩溃时由新 manager 回滚整批文件，提交标记后只清理事务目录；损坏 journal/缺失 backup fail-closed。已通过并行真实 DeveloperAgent + MockLLM 工具循环 E2E；外部 ProviderLLM 集成与共享依赖缓存复用策略延期到 T21.8/后续性能阶段。

### P1：真实多技术栈构建与可执行验收

- [x] **T21.3 Project Adapter 架构（v1 完成，2026-11-14）**：Python 与 Node/npm 适配器注册表及 install/build/test/package/smoke/deploy 动作计划；`supported/skipped/unsupported` 状态；所有命令经 ToolInvocationService 的 `run_command`，1–3600 秒超时；ProjectOrchestrator opt-in 集成门禁、workspace scope、失败返工证据与审计历史；Python/Node fixture 真实命令验证；Windows 生产 PowerShell terminal 验证 task-local venv、build/test/smoke/package 与非零退出码 fail-closed。边界：npm only（pnpm/yarn 明确 unsupported）、缓存仅 lease-local（无跨任务复用）、deploy unsupported；适配器阶段默认关闭，避免未经显式授权的依赖网络访问。
  - 新增统一适配器协议/注册表，至少定义 detect、install、build、test、package、smoke、deploy 能力及明确的 unsupported 状态。
  - 首批实现 Python 与 Node.js；项目类型与语言/框架检测分离，不能仅凭 web/API 分类就假定技术栈。
  - 所有命令经过现有权限策略/沙箱，具备 allowlist、超时、工作目录限制、输出脱敏；不允许 adapter 绕过 ToolInvocationService。
  - 设计说明：[`docs/project_adapter_architecture.md`](docs/project_adapter_architecture.md)。
  - 验收：Python 与 Node.js fixture 项目分别完成依赖安装（离线 fixture 可替代网络安装）、构建、测试、打包和冒烟；未知技术栈明确拒绝或降级。
- [x] **T21.4 Executable Acceptance Evidence（v1 完成，2026-11-14）**
  - `runtime/executable_acceptance.py` 建立 REQ → AT ID → 精确 JUnit selector → 实际执行状态/耗时/摘要的确定性模型；保留集成测试命令、退出码、汇总与证据时间。
  - `runtime/integration_verification.py` 从隔离 staging 的 pytest JUnit XML 读取逐用例结果；DocWriter 只可从本次真实观测到的 REQ 与 selector 生成 `docs/acceptance_tests.json`，既有人工维护映射保持不覆盖。
  - 强制 REQ 无映射、selector 未执行、测试失败、suite 跳过、manifest 非法或证据超过 24 小时均不能通过；`runtime/release_gate.py` 对 `failed/not_executed/stale` 确定性阻断，Release Manager 不能覆盖。
  - 报告：`docs/acceptance_report.md`（文档追溯）与 `docs/executable_acceptance_report.md`（执行证据）。人工 UAT 签核仍是外部人工流程；未接入可验证签名 provider，不计为自动化证据。
  - 验证：通过/失败/未执行/无关联测试/过期/非法 selector/发布阻断契约测试；GitHub Actions run 43606002701：全量回归 2309 passed / 10 skipped，安全回归 234 passed / 9 skipped，Windows 生产终端 smoke 1 passed。
  
### P2：外部协作与部署闭环

- [ ] **T21.5 SCM / PR / CI Provider（进行中；T21.5.1 编排器只读证据接线完成）**
  - 定义 SCM provider 接口，首批支持 GitHub：分支/提交推送、PR 创建/更新、CI 状态读取、review 状态读取、合并前检查。
  - 远端写操作与合并必须受 host-owned 权限边界和显式审批控制；Agent 不得自行扩大 token 权限。
  - CI 失败反馈可转成修复任务，但需限制轮次并保留原始状态证据。
  - 验收：mock provider 全路径契约 + GitHub 最小集成验证；权限不足时 fail-closed。
  - 第一阶段已实现 provider-neutral `SCMProvider` / `SCMService` 与 GitHub REST adapter：分支推送、PR 创建/更新、CI 与 review 状态读取、PR 合并。
  - push / PR 写入 / merge 使用 host-owned 一次性、短时、精确 scope approval；push 绑定分支与本地 HEAD SHA，merge 绑定 PR head SHA 并向 GitHub 发送条件 merge SHA；还要求 CI `success` + review `approved`。Agent 仍无法调用 raw Git `push` / `remote`。
  - 当前已有 mock provider 与 GitHub REST transport 契约测试；尚未完成真实 GitHub test-repository 集成（需要 host token 与人工批准）。CI failure → bounded repair-task proposal 已实现并通过主 CI #489；只生成 blocked host-approval task，不自动执行或重跑 CI。
  - T21.5.1 已接入 `ProjectOrchestrator`：可注入 host-created `SCMService` 与显式 repository/PR 编号；交付阶段只读采集 PR head/state、CI 与 review，写入交付任务上下文。只有 open + unmerged + CI success + review approved 标记 `ready`；非绿标记 `blocked`，远端异常标记 `unavailable`（仅记录异常类型）；不执行 push/PR write/merge，无配置时保持旧行为。新增 `SCMService.get_pull_request` 与 `tests/test_scm_orchestrator.py`。
  - T21.5.2（主机凭证配置与 Provider 生命周期）已完成实现：新增 `runtime/github_scm_config.py`，仅从 `AI_TEAM_GITHUB_TOKEN`、`AI_TEAM_GITHUB_REPOSITORY`、`AI_TEAM_GITHUB_PULL_REQUEST` 构建 opt-in GitHub SCM runtime；未配置时保持禁用，部分配置/缺少 Token/非法 repo 或 PR 编号 fail-closed。CLI 的普通交付与持久化项目修订入口均由 host factory 创建 SCMService 并注入 ProjectOrchestrator；Token 不进入命令行参数、Agent 工具、任务上下文或 runtime repr。GitHub REST 错误详情对可能回显的 Token 做脱敏。新增配置工厂测试覆盖禁用、部分配置、Token 缺失、非法参数和 repr 泄漏；现有 REST transport 测试增强为模拟远端错误回显 Token。凭证无效/权限不足时，PR 观察按 unavailable 处理，不视为成功。当前仍未执行真实 GitHub 凭证验证；本节点 CI 状态待验证。

  - T21.5.4（SCM 生命周期端到端 Mock 验证）已完成测试实现：新增 `tests/test_scm_lifecycle_e2e.py`，使用同一个 provider fixture 串联 push → PR create → CI/Review polling → fresh merge preflight → conditional merge；覆盖 CI failure/pending timeout、Review changes_requested、PR closed、push HEAD 漂移、poll 后 PR head 漂移、poll 后 PR 关闭、PR 创建 API 故障（push 已成功后的部分失败）与 merge API 故障。验证重点是失败路径不执行后续写操作、不自动重试，API 异常如实向上抛出。当前仅通过 GitHub 文件接口写入测试，尚未在本地执行 pytest；CI 待验证。
  - T21.5.3（PR 生命周期协调与 CI/Review 有界轮询）已完成第一阶段：新增 `runtime/scm_lifecycle.py` 的 host-only `SCMLifecycleCoordinator`。发布动作要求两张独立的一次性审批（精确 HEAD 的 push approval、head/base 的 PR approval），先 push 再创建/更新 PR；不由 coordinator 签发审批。新增有界轮询（1–120 次、间隔 0–300 秒），返回 ready / ci_failed / changes_requested / closed / timeout 及对应 head SHA、CI、Review 证据。不会自动重跑 CI、修改 Review、自动修复、push 新提交或 merge；失败证据可供上层生成修复提案，写操作仍需独立审批。新增 mock lifecycle tests 与架构文档。当前仅实现 host-callable coordinator API，尚未提供交互式审批 UI/CLI，也未执行 live GitHub 测试；CI 待验证。
  - T21.5.3 第二阶段已完成：将 PR 状态查询接入 CLI，新增 `--scm-poll-pr NUMBER` 独立只读命令；支持 `AI_TEAM_GITHUB_TOKEN` + `AI_TEAM_GITHUB_REPOSITORY` 主机环境配置，并允许命令行 PR 编号覆盖环境中的默认 PR 编号。CLI 调用 `SCMLifecycleCoordinator` 执行有界 CI/Review 轮询，JSON/文本输出结构化 head SHA、CI、Review、尝试次数与状态；ready 返回 0，blocked/closed/timeout 返回 2，配置/API 错误返回 1。该命令拒绝与交付/其他操作混用，不执行任何 SCM 写操作。新增 `tests/test_scm_cli.py` 及配置工厂覆盖，文档已更新；CI 待验证，未做 live GitHub 凭证验证。
  - T21.5.3 第三阶段已完成：新增独立 `--scm-publish-pr` CLI 发布入口。Host 先读取并展示本地 HEAD SHA、目标仓库、分支、base 和 PR 标题，再要求操作者在真实 TTY 终端分别输入 `yes` 确认精确 SHA 的 push、以及 PR create/update；非交互 stdin 或任一步拒绝均阻止相应写操作。JSON 模式下提示/预览走 stderr，stdout 保持机器可读。Host factory 可在无默认 PR 编号时创建 runtime，并将 `SCMApprovalAuthority` 保留在 host runtime（repr 隐藏）；新增 `SCMService.get_local_head_sha` 供审批前预览。发布流程仍经 `SCMLifecycleCoordinator`，provider 校验 origin 仓库与 HEAD 未漂移。新增 `tests/test_scm_publish_cli.py` 与本地 SHA 契约测试，文档说明 read-only 与 publish 所需最小 GitHub 权限差异。CI 待验证；未使用真实凭证执行 push/PR。
  - T21.5.3 第四阶段已完成：新增 `--scm-merge-pr NUMBER` / `--scm-merge-method` 独立合并命令。命令先进行 PR/CI/Review 有界轮询，仅 `ready` 才允许提示；必须在真实 TTY 输入 `yes`，随后签发绑定 `PR number + exact head SHA` 的一次性 merge approval。`SCMService.merge_pull_request` 再次检查 PR open/unmerged、CI success、Review approved，并把 expected SHA 交给 GitHub 防止 head 漂移；blocked、取消或非交互执行均不签发审批、不发送 merge 请求；poll/publish/merge 三种 SCM CLI 命令互斥，防止组合参数触发错误写路径。新增 `tests/test_scm_merge_cli.py`，加强 provider merge preflight 对 closed/already-merged PR 的拒绝测试，文档已更新。CI 待验证，未执行真实 GitHub merge。
  - T21.5 Mock / CI 验收复核（2026-11-15）：上述 GitHub REST adapter、host 配置、orchestrator 只读证据、CLI poll/publish/merge 与生命周期 E2E mock 契约均已纳入主 CI。run #478（commit `548c94b`）完整成功：全量回归 2,532 passed / 10 skipped，安全回归 237 passed / 9 skipped，覆盖率基线 2,512 passed / 10 skipped 且所有模块行/分支门槛通过，Windows production toolchain smoke 1 passed。由此确认 mock 路径在 CI 中可运行；这不等同于真实 Token/写权限集成。
  - T21.5 Live read-only 阶段：新增 `.github/workflows/scm-live-readonly-smoke.yml` 与 `scripts/scm_live_readonly_smoke.py`，由人工在 Actions 中选择 PR 编号后触发。工作流仅使用当次仓库范围的 `GITHUB_TOKEN`，显式只授予 contents / pull-requests / checks / statuses read；输出脱敏 PR、head SHA、CI 与 review 证据，不执行 push、PR 写入、review 修改或 merge。新增契约测试确认输出脱敏及最小只读权限。该手动工作流尚未由操作者触发，真实 provider 的 live read-only 结果仍待记录；其实现、脚本与权限契约已由 CI #481 验证通过，并在最新综合 CI #489 再次通过：全量回归 2,549 passed / 11 skipped，安全回归 237 passed / 9 skipped，Coverage baseline 2,529 passed / 11 skipped 且模块行/分支门槛全部满足，Windows Python/Node.js 22 adapter E2E 2 passed。
  - 2026-11-15 只读预检：仓库当前可见 PR #2 为 2026-08-22 更新的旧 draft，head `85abdaf906607a2240ebc6bb69b61d0d5b735455`；GitHub 返回 open/draft、无 review、0 check runs 且 combined status pending。它可用于验证 blocked/unknown 响应，但不是 ready happy-path 验收样本；不得据此合并或解除审批门。
  - T21.5 剩余阻塞：需要选择一个受控测试 PR/仓库人工触发上述 live read-only smoke；完整 push → PR create/update → CI/review → conditional merge live 验证仍需专用测试仓库和单独的一次性 host approvals。所有远端写操作保持关闭，不得用 GitHub connector 直接操作替代运行时 adapter 的写路径验收。
  - T21.5 CI 失败到修复任务提案（实现与 CI 验收完成，2026-11-15）：新增 `runtime/scm_ci_repair.py` 的 host-owned `SCMCIRepairTaskFactory`。工厂重新读取 PR 当前 head 与 CI，只接受 open + unmerged + CI failure；生成带原始状态证据快照、SHA-256 digest、捕获时间与 untrusted-data fence 的 Developer Task。每个 repository/PR 默认最多两轮（硬上限五轮），相同证据去重，前一修复任务未进入终态时拒绝下一轮；畸形历史 fail-closed。新 Task 以 `blocked` 状态加入 TaskManager 与 ProjectOrchestrator 计划，必须由 host 显式批准后才可进入 ready queue；不执行 Agent、不消耗 retry budget、不重跑 CI、不执行 SCM 写操作。新增 `TaskManager.add_blocked_task` 与 11 项契约测试。最新 main CI #489（commit `67c9b75`）全绿：全量回归 2,549 passed / 11 skipped，安全回归 237 passed / 9 skipped，Coverage baseline 2,529 passed / 11 skipped 且模块门槛通过，Windows Python/Node.js 22 adapter E2E 2 passed。此项完成；T21.5 整体仍因 live-read-only 与隔离仓库写路径尚未实测而保持进行中。


- [ ] **T21.6 Deployment / Operations Adapters**
  - [x] **T21.6.1 Provider-neutral deployment contract（2026-11-15 完成）**：新增 `runtime/deployment_provider.py`，定义显式部署请求、SHA-256 内容寻址制品、部署记录、健康检查结果、四态操作结果与 host-owned `DeploymentProvider` Protocol；rollback candidate 仅接受曾运行且已验证 healthy 的记录。纯契约模块，不执行 Docker/云 I/O；新增契约校验测试与安全边界文档。
  - [x] **T21.6.2 Local Docker Provider（2026-11-15 完成）**：新增 `runtime/local_docker_provider.py`，通过可注入 `DockerCommandRunner` 执行固定 argv；生产 runner 使用 `subprocess.run(shell=False, timeout=...)`，不使用 sudo。实现 Dockerfile build、image ID SHA-256 校验、镜像身份复核、容器 run/inspect、stop 与 Docker HEALTHCHECK 状态读取；daemon 不可用、构建/启动失败如实区分，缺少 HEALTHCHECK 保持 unknown。新增 fake-runner 测试覆盖无 Docker executable/daemon、构建失败、镜像摘要、启动失败、健康状态与 stop。Rollback 暂返回 unsupported，等待 T21.6.3 Host-owned history。Run #288 已全绿：完整回归、安全回归、Windows production terminal smoke 均通过。
  - [ ] **T21.6.3 Host-owned deployment history and verified rollback（进行中）**：已新增 SQLite host-owned history 与 `HostDeploymentManager`，只持久化成功运行部署并记录健康状态；回滚候选按 provider + environment + project 三重 scope 筛选，旧数据库通过 nullable project 列迁移，缺少 project identity 的旧记录不参与回滚。Agent 不提供 rollback authority。当前 Local Docker rollback 仍 unsupported；已补充显式不可变容器 ID：部署后 inspect 完整容器对象，验证 run 返回 ID 与 inspect ID 一致并持久化到 host history；损坏 inspect 输出/身份不匹配 fail-closed；无 immutable ID 的旧记录不作为 rollback candidate；health_check 与 stop 现在均在读取/操作前通过完整 inspect 对比不可变容器 ID，避免容器名复用导致误判健康或误停新容器。 HostDeploymentManager 在委托 rollback 前还会重新调用 Provider.health_check，持久化最新健康观察；仅 fresh healthy 放行，unhealthy/unavailable/unknown、检查异常或观察无法持久化均 fail-closed。prepare/start/health/traffic-switch/stop-old 安全替换能力仍待实现。SQLite 已增加 POSIX 0600 文件权限、显式连接关闭、并发写 busy timeout、损坏数据库与损坏 JSON fail-closed 测试。CI #291/#292/#293/#295/#299/#300 已通过；#294 为事务提交修复前的失败运行，#295 验证事务修复，#299 验证不可变容器身份 health/stop，#300 验证 rollback 前即时健康复核；均通过完整回归/安全回归与 Windows smoke。未证明流量切换安全前不得宣称支持回滚。
  - 把本地打包、容器构建、镜像扫描/发布、环境部署、健康探针、回滚拆成可替换 adapter。
  - 首批提供本地 Docker 构建/运行/健康检查；云厂商部署作为后续 provider，不宣称未接入的云能力。
  - 回滚必须基于明确的上一个健康版本和可验证的部署记录。
  - 验收：本地容器端到端 fixture；构建失败/健康检查失败/回滚失败均如实报告。
  
### P3：工程质量与真实项目验收

- [ ] **T21.7 供应链与质量门禁增强**（现状评审完成；T21.7.1 可复现依赖锁定已完成并通过双平台 CI；T21.7.2 已完成；T21.7.3 覆盖率门禁已落地，固定硬件性能预算待受控 runner；T21.7.4 漏洞与许可证门禁已完成；详见 `docs/supply_chain_quality_gate_design.md`）
  - [x] T21.7.1：生产/开发依赖完整锁定与哈希校验，CI 使用可复现输入（2026-11-15 完成；Linux/Windows Python 3.14 四份 lock；pip 25.3 + `--require-hashes`；完整回归/安全回归/Windows smoke 全绿）。
  - [x] T21.7.2：生成 CycloneDX 1.6 JSON SBOM，并绑定 lock/artifact/build-evidence digest（2026-11-15 完成；锁文件组件/PURL/SHA-256、declared-only partial、隐私最小化 build evidence、ZIP 外 provenance sidecar、篡改校验均有测试）。
  - T21.7.3：覆盖率基线与模块风险门禁已完成；绝对性能预算暂缓至受控 runner 可用（现有相对扩展性回归保留，10k-task 与真实 Provider 基准为 opt-in；默认 CI 有界）。
  - [x] T21.7.4：仅在 CI 显式网络出口白名单下执行漏洞/许可证扫描；scanner unavailable、数据库过期、未知许可证不得视为 clean（2026-11-15 完成：pip-audit 2.10.1 + OSV API；Trivy 0.76.2 license scan；17 包、0 个已知漏洞、OSV freshness 通过；`tqdm==4.70.1` 的精确 `MPL-2.0 AND MIT` 例外经 owner 有条件批准，保留 RECIPROCAL 分类并设 2027-02-13 复审/到期；未放宽其他类别）。
  - 验收：锁/哈希不符、SBOM schema 错误、阈值阻断、工具不可用、网络拒绝、许可证冲突等场景均如实输出；不得引入自动依赖升级或隐式公网出口。
- [ ] **T21.8 Real Project E2E**
  - 选取 Python CLI/API 与 Node.js Web 两类代表项目，从自然语言需求启动完整交付。
  - 检查需求追溯、隔离开发、构建测试、可执行验收、QA/安全、打包、发布记录与交付说明。
  - 输出能力边界报告，明确哪些步骤由本地执行、哪些依赖用户凭证/环境/人工审批。
  - 2026-11-15 现状评审：Python 已有 Windows 真实命令链路 smoke；Node.js 已有 adapter/lease 隔离契约，但尚无完整 Web 项目交付验收。新增 `docs/real_project_e2e_acceptance.md`，定义 Python CLI/API 与 Node.js Web 两个场景、生产 ToolInvocationService 命令边界、可执行验收证据、失败/安全矩阵，以及 MockLLM deterministic E2E、Live ProviderLLM 和外部部署三种证据级别。该文档仅完成验收规范，不代表真实项目 E2E 已通过；下一步实现两个场景的确定性端到端运行与证据归档。

## 21.3 优先级与停止条件

1. 先完成 T21.1 并恢复可用 CI；CI 未绿，不进入后续大规模重构。
2. T21.2 与 T21.3 是通用交付能力的核心阻塞项，优先于增加 Agent 角色。
3. T21.4 是发布可信度门槛；没有可执行证据不得把文档追溯等同于功能验收。
4. T21.5/T21.6 需要外部凭证或真实环境时，先完成接口与 mock 契约；真实集成需凭证到位后再验证。
5. 每一节点独立提交到 `main`；不做历史分支整合，不批量重写无关模块。
6. 如果安全边界、现有测试契约或数据兼容性无法证明，暂停该节点并记录阻塞，不以弱化测试换取通过。


| 2026-11-15 | T21.7.1 dependency input inventory | 核对 requirements、CI 安装步骤与安装文档。确认 production requirements 仅 pin 两个直接依赖，dev requirements 使用范围约束，CI 升级 pip 后在线解析；setup guide 还引用仓库中不存在的 requirements-mcp.txt。修正文档，明确 MCP bridge 为外部项目，并如实说明当前尚无传递依赖锁/哈希验证；新增文档契约测试。完整 lock 生成暂缓，需在受控 Python 3.14 环境解析并验证 Windows/Linux 目标平台及 hash，不能猜测传递版本或伪造 hash。 | 提交 `695c7a3`、`54635a9`；CI 待验证 |

## 21.4 Phase 21 执行记录

| 2026-11-15 | T21.6.3 项目隔离与 SQLite 加固 | #292/#293 全绿；按 provider/environment/project 过滤历史，迁移旧 schema 并重建索引。继续增加数据库权限、连接生命周期、并发写与损坏数据 fail-closed 验证。 | [CI #292](https://github.com/rexyll/AI-Team/actions/runs/43674639086)、[CI #293](https://github.com/rexyll/AI-Team/actions/runs/43674660217)；提交 `0ad2430`、`8c7b98e` |

| 2026-11-15 | T21.6.3 CI #291 + foreign-provider test correction | CI 全绿：regression (3.14) 与 Windows toolchain smoke 均成功；修正测试使 foreign provider record 内部一致，从而实际覆盖 HostDeploymentManager 配置 Provider 拒绝路径。 | [GitHub Actions #291](https://github.com/rexyll/AI-Team/actions/runs/43674299436)；提交 `0ea0a7a` |

| 日期 | 节点 | 结果 | 证据 |
|---|---|---|---|
| 2026-11-15 | T21.6.3 CI #290 失败分析 | 全量回归 2421 passed / 1 failed / 10 skipped；安全回归 234 passed / 9 skipped；Windows smoke 通过。失败发生在测试构造 `DeploymentOperationResult` 时：其自身不变量先拒绝 result.provider 与 record.provider 不一致，HostDeploymentManager 尚未执行。修正测试为构造内部一致但 provider 与 Host 配置不一致的 foreign record，并验证 manager 拒绝且不落库。 | [GitHub Actions #290](https://github.com/rexyll/AI-Team/actions/runs/43674078108) |
| 2026-11-15 | T21.6.3 CI #289 失败分析 | 全量回归 2421 passed / 1 failed / 10 skipped；安全回归 234 passed / 9 skipped；Windows smoke 通过。唯一失败为非配置 Provider 被拒绝时，异常文案未满足 `configured` 语义断言；拒绝逻辑本身生效。修复生产错误信息后重新验证。 | [GitHub Actions #289](https://github.com/rexyll/AI-Team/actions/runs/43673851910)；`tests/test_deployment_history.py::test_manager_persists_only_success_from_configured_provider` |
| 2026-11-15 | T21.6.2 CI #288 复验 | 修复 `Docker executable not found` 的 unavailable 分类后，全量回归、安全回归及 Windows production terminal smoke 全部通过，T21.6.2 正式完成。 | [GitHub Actions #288](https://github.com/rexyll/AI-Team/actions/runs/43673627435)；提交 `411db82` |\n| 2026-11-15 | T21.6.2 CI #287 失败分析 | 全量回归 2414 passed / 1 failed / 10 skipped；安全回归 234 passed / 9 skipped，Windows smoke 通过。失败表明生产分类逻辑遗漏 `Docker executable not found`，将 Docker CLI 缺失误报为 `failed` 而非 `unavailable`；已修复 `_is_unavailable` 标记列表，需新 CI 复验。 | [GitHub Actions #287](https://github.com/rexyll/AI-Team/actions/runs/43673340571)；更新 `runtime/local_docker_provider.py` |\n| 2026-11-15 | T21.6.2 CI #286 失败分析 | 全量回归 2414 passed / 1 failed / 10 skipped；失败仅为 `test_missing_docker_executable_is_unavailable` 的测试夹具未创建 Dockerfile，导致 Provider 在 Docker runner 调用前按预期拒绝输入；安全回归 234 passed / 9 skipped，Windows smoke 通过。已修正夹具，需新 CI 复验，T21.6.2 暂不勾选完成。 | [GitHub Actions #286](https://github.com/rexyll/AI-Team/actions/runs/43673187511)；更新 `tests/test_local_docker_provider.py` |
| 2026-11-15 | T21.6.2 Local Docker Provider | 实现完成，CI 待验证；固定 argv + shell=False + timeout 的 host runner；构建以 Docker image ID SHA-256 作为制品身份，部署前复核镜像 ID；容器运行态与 Docker HEALTHCHECK 分开处理，无 HEALTHCHECK 不等于 healthy；daemon unavailable、build/start failure 明确区分；rollback 暂不支持，等待 host-owned history。 | 新增 `runtime/local_docker_provider.py`、`tests/test_local_docker_provider.py`；更新 `docs/deployment_provider_architecture.md`、`TaskPlan.md` |
| 2026-11-15 | T21.5.4 SCM lifecycle mock E2E + CI 修复 | CI 已通过：修复 publish CLI 测试使用真实 `SCMService` 的测试夹具，以及 PR 创建失败路径的事件顺序断言。全量回归 2394 passed / 10 skipped；安全回归 234 passed / 9 skipped；Windows production terminal smoke 通过。仅 mock 验证，未执行真实 GitHub push/PR/merge。 | [GitHub Actions #283](https://github.com/rexyll/AI-Team/actions/runs/43672101456)；提交 `7af42e6`；`tests/test_scm_publish_cli.py`、`tests/test_scm_lifecycle_e2e.py` |
| 2026-11-15 | T21.5.3 CI-gated interactive merge CLI | 实现完成，CI 待验证：只允许 open/unmerged + green CI + approved review；真实 TTY 二次确认、head-SHA 一次性审批、merge 前再次 preflight；未做 live merge。 | 更新 `main.py`、`runtime/scm_provider.py`、`tests/test_scm_provider.py`、`docs/scm_provider_architecture.md`；新增 `tests/test_scm_merge_cli.py` |
| 2026-11-15 | T21.5.3 interactive publish approval CLI | 实现完成，CI 待验证：独立 `--scm-publish-pr` 入口、精确 HEAD 预览、push 与 PR 两次独立确认、双一次性审批、origin/HEAD 校验；未做 live GitHub 写操作。 | 更新 `main.py`、`runtime/github_scm_config.py`、`runtime/scm_provider.py`、`tests/test_github_scm_config.py`、`tests/test_scm_provider.py`、`docs/scm_provider_architecture.md`；新增 `tests/test_scm_publish_cli.py` |
| 2026-11-15 | T21.5.3 PR polling CLI integration | 实现完成，CI 待验证：独立只读 `--scm-poll-pr` 命令、显式 PR 编号覆盖、JSON/文本输出及状态退出码；无 SCM 写操作，未做 live GitHub 验证。 | 更新 `main.py`、`runtime/github_scm_config.py`、`tests/test_github_scm_config.py`、`docs/scm_provider_architecture.md`；新增 `tests/test_scm_cli.py` |
| 2026-11-15 | T21.5.3 PR lifecycle coordinator v1 | 实现完成，CI 待验证：独立 push/PR 一次性审批、host-only PR 创建/更新、CI/Review 有界轮询与结构化终态；无自动重试/修复/merge，未做 live GitHub 验证。 | 新增 `runtime/scm_lifecycle.py`、`tests/test_scm_lifecycle.py`；更新 `docs/scm_provider_architecture.md` |
| 2026-11-15 | T21.5.2 GitHub host credential config / factory | 实现完成，CI 待验证：环境变量 opt-in factory、CLI 普通交付与项目修订接线、缺失/部分/非法配置 fail-closed、Token 不进入 Agent/task/repr、HTTP 错误回显脱敏；未进行 live GitHub 凭证验证。 | 新增 `runtime/github_scm_config.py`、`tests/test_github_scm_config.py`；更新 `main.py`、`runtime/github_scm_provider.py`、`tests/test_github_scm_provider.py`、`docs/scm_provider_architecture.md` |
| 2026-11-14 | T21.5.1 ProjectOrchestrator SCM 接线（只读观察） | 实现完成，CI 待验证：注入式 SCMService + 显式 repo/PR 配置；交付阶段记录 PR head/state、CI、review 证据；仅全绿标记 ready，异常记录 unavailable，不执行任何写操作；无配置保持旧行为。新增 service PR metadata read 与 orchestrator contract tests。GitHub connector 当前未返回该提交的 check/status 或 workflow run，不能据此宣称测试通过。 | 提交 `7163d32`、`311a826`、`23f3b2b`、`8f52d89`、`3e3b1e8`；`tests/test_scm_provider.py`、`tests/test_scm_orchestrator.py` |
| 2026-11-14 | 基线复核与 Phase 21 计划 | 已定义；待逐项执行 | 本文件 |
| 2026-11-14 | T21.1 CI 基线修复 | 完成；全量回归 2236 passed / 9 skipped；安全回归 233 passed / 9 skipped | [GitHub Actions #9](https://github.com/rexyll/AI-Team/actions/runs/43586159954)，提交 `518e3f3` 及前序 CI 修复提交 |
| 2026-11-14 | T21.2 Developer Workspace 隔离（v1 完成） | 跨进程租约/事务回滚/崩溃恢复通过；任务级 Python venv、Node node_modules、pip/npm lease-local cache；依赖目录不复制、不合并、不进入交付/冒烟 staging；安装失败 fail-closed。并行真实 DeveloperAgent + MockLLM 工具循环验证两份独立 lease、write_file 工具调用、源码合并与环境回收。全量回归 2284 passed / 10 skipped；安全回归 234 passed / 9 skipped；Windows 生产 terminal 1 passed。剩余边界：无跨任务缓存复用；外部 ProviderLLM 集成留待 T21.8 | [GitHub Actions run 43600653338](https://github.com/rexyll/AI-Team/actions/runs/43600653338)；新增 `runtime/project_environment.py`、`tests/test_project_environment.py` 与依赖目录排除回归 |
| 2026-11-14 | T21.4 Executable Acceptance Evidence（v1 完成） | JUnit 逐用例执行证据、REQ/AT/selector 映射、24h 过期检测与确定性发布门禁完成；DocWriter 映射生成受已观测 selector 约束；人工签名 UAT provider 暂未接入。全量回归 2309 passed / 10 skipped；安全回归 234 passed / 9 skipped；Windows smoke 1 passed | [GitHub Actions run 43606002701](https://github.com/rexyll/AI-Team/actions/runs/43606002701)；新增 `runtime/executable_acceptance.py`、`docs/executable_acceptance_evidence.md` 与执行证据契约测试 |
| 2026-11-14 | T21.5 SCM / PR / CI Provider（接口与 GitHub adapter 第一阶段） | provider contract、GitHub REST adapter、host-only 非强制 push、短时一次性审批、CI/review preflight 与精确 head-SHA merge scope 已实现；live GitHub 尚未验证，CI 失败自动返工未接入 | 新增 `runtime/scm_provider.py`、`runtime/github_scm_provider.py`、`docs/scm_provider_architecture.md` 与 mock contract tests |
| 2026-11-14 | T21.3 Project Adapter 架构（v1 完成） | Linux 全量回归 2284 passed / 10 skipped；安全回归 234 passed / 9 skipped；Windows 生产 terminal 1 passed（task-local venv、build/test/smoke/package + 非零退出码 fail-closed）；Python/Node npm fixture 经 ToolInvocationService 完成 install/build/test/package/smoke；ProjectOrchestrator opt-in 集成门禁、workspace scope、失败返工证据与审计历史完成。边界：npm only；pnpm/yarn 与 deploy unsupported；缓存仅 lease-local | [GitHub Actions run 43600653338](https://github.com/rexyll/AI-Team/actions/runs/43600653338)；新增适配器/环境 provisioner/编排与 Windows E2E 测试 |

| 2026-11-15 | T21.6.3 rollback 前即时健康复核 | 已加入 HostDeploymentManager rollback preflight：不再仅信任历史 healthy 标记；调用 provider 重新检查候选的 immutable runtime identity/current health，并先持久化观察。只有 fresh healthy 才委托 provider；非健康状态、检查异常或持久化失败均阻断。Local Docker rollback 仍 unsupported。 | 新增 fresh-health rollback tests；CI 待验证 |


| 2026-11-15 | T21.6.3 rollback 即时健康复核 CI | Run #300 全部 Job 成功；regression (3.14) 与 Windows toolchain smoke 均通过。 | [GitHub Actions #300](https://github.com/rexyll/AI-Team/actions/runs/43676556207)；提交 `b807b6f` |
| 2026-11-15 | T21.6.3 安全替换设计门禁 | 明确 rollback 必须是 host-owned replacement transaction：双实例身份、候选隔离启动、候选健康验证、路由切换与 read-back、旧实例退役、失败补偿、持久化事务日志和并发 CAS。当前 history 缺少 active deployment 状态与 replacement journal，Docker 也没有 host-owned traffic router，因此本阶段继续保持 rollback unsupported；先补齐状态模型/协议，再做 daemon-backed E2E。 | 更新 `docs/deployment_provider_architecture.md` |


| 2026-11-15 | T21.6.3 granular replacement contract | 新增独立 `DeploymentReplacementProvider` capability，拆分 candidate prepare/start/health、traffic switch/read-back、retire previous、abort；新增 replacement phase 与双 deployment/runtime identity journal 数据契约及校验测试。该提交仅定义协议，不表示已有 provider 实现或持久化 journal；Local Docker rollback 继续 unsupported。 | 新增 `runtime/deployment_replacement.py`、`tests/test_deployment_replacement.py`；更新部署架构文档与 TaskPlan；CI 待验证 |


| 2026-11-15 | T21.6.3 durable replacement journal | SQLite 新增 replacement journal 表；仅 prepared 可创建事务；provider/project/environment 维度 partial unique index 保证每个 scope 最多一个非终态替换（needs_reconciliation 持续占用）；阶段更新使用 expected-phase CAS，校验允许的阶段迁移并禁止 scope/deployment/runtime identity 重写；支持重启后读取 journal。新增持久化、CAS 冲突、身份不可变、scope 隔离、终态释放与并发单赢家测试。尚未实现崩溃自动恢复、active deployment 唯一约束或 Docker router；rollback 仍 unsupported。 | 更新 `runtime/deployment_history.py`、`tests/test_deployment_replacement.py`、部署架构文档与 TaskPlan；CI 待验证 |


| 2026-11-15 | T21.6.3 explicit active deployment pointer | 增加独立 `active_deployments` 表，按 provider/environment/project 唯一定位当前 host-observed 流量归属；通过 expected-current-ID CAS 原子切换/清除，校验候选记录确属相同 scope 且 status=running；部署 ID 不能跨 scope 重复激活。旧数据库只创建空表，不从历史 running 记录推断 active。该指针不代表实时健康或路由已验证，只有 host 在路由 read-back 后才能写入；Docker rollback 继续 unsupported。 | 更新 `runtime/deployment_history.py`、`tests/test_deployment_history.py`、部署架构文档与 TaskPlan；CI 待验证 |


| 2026-11-15 | T21.6.3 CI #304 failure correction | 根据 regression (3.14) 的 2 个失败定位到新增测试前提错误：history.append 本来就拒绝非 running 记录；另一个测试把 scope 校验错误地期待成 SQLite 唯一约束异常。修正测试为验证既有契约和跨 scope 读取/激活拒绝，不放宽生产代码约束。 | 待 CI 复验 |


| 2026-11-15 | T21.6.3 replacement journal implementation correction | 复核发现先前计划/架构文档曾把 replacement journal 记为已完成，但 `DeploymentHistoryStore` 实际缺少对应 API。现补齐 SQLite 表、scope partial unique index、prepared-only begin、允许阶段图、expected-phase CAS、不可变 scope/runtime identity 校验、重启读取与 active journal 列表；`needs_reconciliation` 持续占用 scope，终态释放。新增持久化、非法初始阶段、scope 互斥、CAS、身份篡改、终态释放和 reconciliation 阻塞测试。尚未实现自动恢复或 provider 执行器。 | CI 待验证 |


| 2026-11-15 | T21.6.3 CI #305 follow-up | CI #305 仅剩一项测试错误：测试先验证 append 拒绝 stopped 记录，随后又尝试将未入库的该 ID 设为 active，生产 API 正确抛出 KeyError。移除不成立的第二断言，保留非 running 入库拒绝与错误 scope 激活拒绝两项有效覆盖。 | CI #306 待验证 |


| 2026-11-15 | T21.6.3 read-only crash recovery classification | 新增纯函数 `classify_replacement_recovery`：根据 journal phase 输出只读处置分类、必须重新观测的 provider/health/route 检查及缺失 runtime identity；prepared/candidate_started 不推断外部动作未发生，traffic_switched 必须 route read-back 后才允许考虑 retire，needs_reconciliation 要求人工决策，终态不恢复。所有阶段均 automatic_action=none；不调用 provider、不改流量、不 abort/retire、不修改 journal。 | 新增 `runtime/deployment_recovery.py`、`tests/test_deployment_recovery.py`；更新部署架构文档；CI 待验证 |


| 2026-11-15 | T21.6.3 recovery classifier hardening | CI #309（run `43681548085`）通过：Python 3.14 regression 与 Windows toolchain smoke 均成功。审查发现 classifier 的兜底分支会把未知/损坏 phase 错误归类为 terminal；现改为仅 `previous_retired`/`aborted` 明确终态，其余未知 phase 抛出 `ValueError` fail-closed。强化 prepared 与 candidate_started 的 phase-specific 检查断言，并新增未知 phase 拒绝测试。 | 本次提交后等待 CI 验证 |


| 2026-11-15 | T21.6.3 CI #310 与恢复边界复核 | CI #310（run `43682013985`，提交 `faf3d6c`）通过：Python 3.14 regression、Windows toolchain smoke 均成功。复核确认 `needs_reconciliation` 仍由 partial unique index 视为非终态并持续占用 scope；列表查询也保留该状态。当前不增加可直接改写事务阶段的人工“解锁”接口：在身份认证、审计主体、外部状态证据及双人/审批策略未定义前，人工备注不能改变 phase 或释放 reservation。 | 只读分类器与 durable journal 已有 CI 证据；下一步需先定义审计/授权契约再实现 reconciliation 操作 |


| 2026-11-15 | T21.6.3 reconciliation authorization design gate | 完成现有能力盘点：SCMApprovalAuthority 是进程内、短时、一次性、按操作/仓库/目标绑定的审批，但 approved_by 仍是调用方字符串，不构成身份认证；DurableDeliveryAuditStore 是追加式 JSONL，但没有防篡改链、可信主体认证或强制持久化证明；ToolPermissionPolicy 是工具能力白名单，不是操作者身份系统。因此这些原语不能直接授权部署事务解锁。确定后续契约必须先接入可信 host-authenticated principal，再采用双人/独立审批（申请人与批准人分离）、精确 scope/operation/journal phase/runtime identity 绑定的一次性短时审批，以及只追加审计事件；每项终态决议必须附 provider 与路由 read-back 的结构化证据摘要。当前仅定义设计门槛，不新增 mutation/unlock API，不改变 journal phase 或 reservation。 | 代码/文档盘点；CI #311 已通过；下一步先定义纯数据契约与验证测试，再讨论执行接口 |


| 2026-11-15 | T21.6.3 reconciliation data contract | 新增纯数据契约：host-authenticated principal 快照、申请人与批准人分离的审批快照、精确绑定 needs_reconciliation scope/phase/deployment/runtime identity 的审批、SHA-256 与时间戳证据引用、两种受限 resolution proposal。abort_candidate 必须有 provider inspection、candidate absence、previous runtime inspection 和 previous route read-back；confirm_previous_retired 必须有 provider inspection、candidate route read-back、candidate health 和 previous retirement。严格拒绝 scope/identity 不匹配、重复/缺失证据、错误 runtime 目标和无效时间/摘要。此模块不认证身份、不签发/消费审批、不验证外部证据、不写审计、不修改 journal、不操作 provider；proposal 不是执行许可。 | 新增 runtime/deployment_reconciliation_contract.py、tests/test_deployment_reconciliation_contract.py；更新架构文档与 TaskPlan；CI 待验证 |


| 2026-11-15 | T21.6.3 reconciliation audit envelope contract | 新增纯数据审计信封：规范化 JSON payload、SHA-256 event digest、连续序号/前序 digest 链接、principal/approval/scope/runtime identity、proposal/evidence digest 与时区时间戳；验证单事件摘要与相邻事件链关系。明确无密钥签名、无受保护链头、无持久化 writer/fsync、无认证/审批消费、无 journal mutation；未锚定的无密钥 hash chain 不能抵御有能力重写整个存储的攻击。 | 新增 `runtime/deployment_reconciliation_audit.py`、`tests/test_deployment_reconciliation_audit.py`；更新部署架构文档；CI 待验证 |


| 2026-11-15 | T21.6.3 audit durability/transaction design review | 检查 SQLite history 的独立事务边界与 JSONL delivery audit 的 flush-only 行为；明确审计事件与 journal CAS 的原子性缺口、外部 ledger 的幂等恢复要求，以及本地 hash chain 必须依赖独立可信链头才能提供篡改检测。确定优先评估同一 SQLite connection/transaction 原子提交审计事件与 journal CAS，但必须另行定义同步/故障模型和外部完整性锚。 | 仅更新架构文档和计划；未新增 writer/table/mutation API；CI 待验证 |

| 2026-11-15 | T21.6.3 audit design CI confirmation | CI #318（run `43684702266`，提交 `17c82d6`）与 CI #319（run `43684713460`，提交 `0bf3367`）均通过；Windows toolchain smoke 与 Python 3.14 regression 全绿。T21.6.3 仍不具备 reconciliation mutation 所需可信身份/双人审批/独立完整性锚，Local Docker rollback 继续 unsupported。 | [CI #318](https://github.com/rexyll/AI-Team/actions/runs/43684702266)、[CI #319](https://github.com/rexyll/AI-Team/actions/runs/43684713460) |


| 2026-11-15 | T21.7 supply-chain and quality-gate assessment | 完成代码与 CI 现状盘点：已有宽松性能扩展性回归和 requirements 顶层版本 pin，但无覆盖率阈值、完整依赖锁/哈希、标准 SBOM、漏洞数据库或许可证扫描。制定四个子节点与安全边界；本记录仅完成评审，不将 T21.7 标记完成。 | 新增 `docs/supply_chain_quality_gate_design.md`；CI 待验证 |


| 2026-11-15 | T21.7.1 dependency lock inventory and CI confirmation | CI #322 (run `43696282821`)、#323 (`43696284854`)、#324 (`43696305155`) 均完成且成功；Python 3.14 regression 与 Windows toolchain smoke 全绿。确认 `requirements.txt` 仅 pin 两个直接依赖，`requirements-dev.txt` 仍为版本范围，CI 当前在线解析传递依赖。修正 setup 文档中不存在的 MCP requirements 引用并增加文档契约测试。完整 lock/hash 尚未生成：必须由真实 resolver 在 Python 3.14 Linux/Windows 环境解析并验证，不能手工编造版本或哈希；T21.7.1 保持进行中。 | 提交 `695c7a3`、`54635a9`、`508c296`；[CI #322](https://github.com/rexyll/AI-Team/actions/runs/43696282821)、[CI #323](https://github.com/rexyll/AI-Team/actions/runs/43696284854)、[CI #324](https://github.com/rexyll/AI-Team/actions/runs/43696305155) |

| 2026-11-15 | T21.7.1 lock generation strategy | CI #325（run `43696563274`，提交 `855b1e0`）全部成功：Python 3.14 regression、安全回归及 Windows toolchain smoke 均通过。进一步确定锁文件必须按 Ubuntu/Windows Python 3.14 分别由 resolver 生成，保留生产/开发输入与解析输出分离，固定 bootstrap/resolver 工具，并由 CI 使用 `--require-hashes` 消费；在实际双平台解析、clean install 和回归验收前不切换 CI、不宣称 lock 完成。 | 更新 `docs/supply_chain_quality_gate_design.md`；[CI #325](https://github.com/rexyll/AI-Team/actions/runs/43696563274) |


| 2026-11-15 | T21.7.1 cross-platform lock resolver workflow | 新增手动触发的 GitHub Actions 工作流，在 Ubuntu/Windows Python 3.14 runner 上使用固定版本 pip 25.3 与 pip-tools 7.5.2 分别解析生产/开发依赖，生成带完整哈希的候选 lock，并上传独立 artifacts；同时记录 resolver 环境。该工作流只产出候选物，不自动提交、不切换主 CI；需检查两个平台产物、执行 require-hashes clean install 与回归后才能接纳。 | 新增 `.github/workflows/dependency-lock.yml`；提交 `8b7fae9`；等待手动 dispatch 与 artifact 审查 |


| 2026-11-15 | T21.7.1 candidate lock review and resolver hardening | 首轮双平台 artifacts 已生成（Linux #14155067621、Windows #14155640489），但未接纳：pip-compile 报告 setuptools 未 pin，且生成头部隐式带有 --no-index。已修订生成流程，显式禁用 pip-tools 配置、固定官方 PyPI index、启用 --allow-unsafe 将 setuptools 纳入哈希锁，并在全新 venv 中分别对生产/开发锁执行 pip install --require-hashes。首轮候选仅用于审查，等待新双平台 run 重新生成并完成 clean-install 验证。 | 更新 `.github/workflows/dependency-lock.yml`；提交 `8e8ecef`、`12e27c0`；新 run 待验证 |

| 2026-11-15 | T21.7.1 cross-platform lock candidates validated | 修订后的 lock workflow run `43698387039` 成功：Linux 与 Windows Python 3.14 两个 Job 均完成 resolver、生产/开发 lock 生成、全新 venv `pip install --require-hashes` 验证及 artifact 上传；同一提交 CI run `43698386997` 也成功。检查 artifact：Linux production/dev 分别 17/30 包，Windows production/dev 分别 18/31 包；开发锁包含 `setuptools==84.2.1` 及 SHA-256 hashes。当前候选验证已通过；新增 workflow 聚合 job，只有两个平台 job 成功后才下载四份锁并提交到 main。仍需检查自动提交结果，再将主 CI 切换为平台对应的 hash-locked dev lock 并运行完整回归。 | [lock generation](https://github.com/rexyll/AI-Team/actions/runs/43698387039)、[CI](https://github.com/rexyll/AI-Team/actions/runs/43698386997)；artifact IDs `14154433979` / `14155348364`；workflow 聚合提交待运行 |
| 2026-11-15 | T21.7.1 lock files committed and CI switched | 双平台 lock 生成 run `43698973027` 成功（Linux/Windows resolver、生产/开发生成、clean venv `--require-hashes` 安装和 artifact 聚合提交均成功）；正式锁文件已由自动化提交 `5f80cd2` 写入 main：`requirements-linux-py314.lock`、`requirements-dev-linux-py314.lock`、`requirements-windows-py314.lock`、`requirements-dev-windows-py314.lock`。随后将 `.github/workflows/ci.yml` 改为固定 pip 25.3 并使用对应平台开发 lock + `--require-hashes` 安装，取代在线解析 requirements 输入。此刻仍需验证切换后的主 CI 完整回归与 Windows smoke；通过前不将 T21.7.1 标记完成。 | lock workflow [run 43698973027](https://github.com/rexyll/AI-Team/actions/runs/43698973027)；lock commit `5f80cd2`；CI 切换 commit `0fcfadb`，待验证 |
| 2026-11-15 | T21.7.1 hash-lock CI regression contract repair | 首次主 CI 锁文件迁移 run `43699113464` 中：Linux/Windows 两边依赖均成功按 hash lock 安装，Windows terminal smoke 成功，安全回归 234 passed / 9 skipped；全量回归 2497 passed / 10 skipped，但 `tests/test_production_configuration_contract.py` 仍断言旧的 requirements 在线安装命令，导致 1 项测试失败。已将该契约改为检查 pip 25.3、`--require-hashes` 和 Linux/Windows 对应开发锁，并断言旧安装命令不再出现。此为迁移后测试契约更新，不是跳过或放宽测试；等待新 CI 全量验证。 | CI failure [run 43699113464](https://github.com/rexyll/AI-Team/actions/runs/43699113464)；测试修复提交 `216faa9`，待验证 |
| 2026-11-15 | T21.7.1 cross-platform dependency lock completed | 四份平台/用途锁文件由 Python 3.14 Ubuntu/Windows runner 上的 pip-tools 7.5.2 真实解析生成，完整传递依赖均带 SHA-256 hash；两个平台生产/开发 lock 均在全新 venv 中通过 `pip install --require-hashes`。自动聚合 job 提交 lock 文件 `5f80cd2`。主 CI 固定 pip 25.3，分别使用 `requirements-dev-linux-py314.lock` 与 `requirements-dev-windows-py314.lock`。迁移后首轮回归发现旧测试仍期待在线 requirements 安装，已更新测试契约而未跳过测试；最终 CI #... 全量回归、安全回归、Windows smoke 全部成功。安装指南、生产配置和供应链设计文档已同步更新。T21.7.2 SBOM、T21.7.3 coverage/performance gate、T21.7.4 vulnerability/license scan 仍未完成。 | [CI run 43699240235](https://github.com/rexyll/AI-Team/actions/runs/43699240235)；lock commit `5f80cd2`；CI migration `0fcfadb`；测试契约修复 `216faa9` |
| 2026-11-15 | T21.7.1 setup documentation contract repair | 最新文档同步 CI run `43699475410` 中，Windows smoke 成功，安全回归成功；全量回归报告 2497 passed / 10 skipped / 1 failed。唯一失败是 `tests/test_production_configuration_contract.py::test_setup_guide_states_real_dependency_contract` 仍断言 setup guide 必须包含旧 `pip install -r requirements.txt`。已将其改为要求 Windows production/dev lock、`--require-hashes` 与顶层输入说明；不改变生产逻辑、不跳过测试。等待最新 CI 复验。 | [失败 CI](https://github.com/rexyll/AI-Team/actions/runs/43699475410)；修复提交 `d33d0ea` |
| 2026-11-15 | T21.7.2 SBOM design gate | 盘点 `runtime/dependency_scan.py` 与 delivery pipeline：当前所谓 SBOM 只是 requirements 顶层摘要，不是标准 SPDX/CycloneDX，也没有 PURL/hash/lock/artifact 绑定。确定 CycloneDX 1.6 JSON；从平台 lock 构建完整组件，缺 lock 时只允许标记 partial，坏 lock fail-closed；将结构化 build evidence 单独规范化并摘要；SBOM 随 ZIP，最终 archive digest 通过 ZIP 外 provenance sidecar 绑定，避免自引用循环。明确 sidecar 无签名，只提供完整性校验。 | 更新 `docs/supply_chain_quality_gate_design.md`；提交 `09044ff`；代码实现待开始 |
| 2026-11-15 | T21.7.2 CycloneDX SBOM and provenance completed | 新增 `runtime/delivery_sbom.py`：生成 CycloneDX 1.6 JSON，优先从平台锁解析完整依赖组件、PyPI PURL、版本、SHA-256 hashes 和环境 markers；无 lock 时只输出明确标记 `partial` 的 declared-only inventory，存在坏 lock 或未展开 requirements include 时 fail-closed。生成 privacy-minimized `DELIVERY_BUILD_EVIDENCE.json`，SBOM 绑定 requirements/lock/build-evidence digest；SBOM 与 evidence 纳入 delivery manifest/ZIP。ZIP 完成后生成 ZIP 外 `.provenance.json` sidecar，绑定 archive、SBOM、manifest、build evidence、lock 摘要并验证成员一致性；sidecar 明确 unsigned，不宣称真实性。全量测试覆盖四份真实 lock、PURL normalization、hash、marker、partial/fail-closed、determinism、tamper detection；CI run `43700797699` 通过：2507 passed / 10 skipped，security 234 passed / 9 skipped，Windows smoke 1 passed。 | [CI run 43700797699](https://github.com/rexyll/AI-Team/actions/runs/43700797699)；实现提交 `65350f9`、`021662d`、`b3d462d`、`b1504f1`、`022f289`、`15cff3c`；T21.7.3/T21.7.4 仍未完成 |
| 2026-11-15 | T21.7.3 line/branch coverage baseline and risk floors | coverage.py 已加入开发依赖并通过 Linux/Windows Python 3.14 hash lock。CI 新增独立 coverage-baseline job，测量 agents/core/runtime/security/tools 的行与分支覆盖率，归档 JSON/HTML/metadata 30 天；coverage source 排除 6 个机器时间敏感 benchmark 测试文件和 3 个 CI-only helper source（helper unit tests 仍执行）。基线 run `43704029101` 全绿：总行覆盖 84.40%（15,795/17,991），分支覆盖 74.99%（4,861/6,482）；模块风险底线分别为 agents 80/68、core 85/68、runtime 83/70、security 70/60、tools 65/58（line/branch），检查器对缺失/未配置模块 fail-closed。全量回归 2,526 passed / 10 skipped，安全回归 237 passed / 9 skipped，Windows smoke 1 passed。性能方面确认现有宽松相对扩展性回归仍运行；10k-task 与真实 Provider 基准 opt-in。因无固定性能 runner，不设置绝对机器时间预算，T21.7.3 保留部分未完成状态。 | [CI run 43704277710](https://github.com/rexyll/AI-Team/actions/runs/43704277710)；coverage artifact `14158465325`；提交 `ff8d1c6`、`fc8c934`、`dab1d7f` |
| 2026-11-15 | T21.7.4 OSV/Trivy production scan | Linux/Windows dev locks 已加入 pip-audit 2.10.1；独立 security workflow 在 Harden-Runner v2.21.1 block egress 下运行。最新完整 scan run `43703756088` 扫描 production lock 17 包：pip-audit 0 vulnerabilities；OSV PyPI export `Last-Modified` 与 latest advisory API record 对齐，freshness 约 1.09h；Trivy license scan 17 包。PSF-2.0 经 SPDX 证据映射为 NOTICE；唯一剩余阻断项是 tqdm 的 MPL-2.0 AND MIT（RECIPROCAL），未加豁免，T21.7.4 不标完成。Trivy OCI DB 连接失败后改用 OSV API，未放宽 egress。 | [Security scan run 43703756088](https://github.com/rexyll/AI-Team/actions/runs/43703756088)；artifact `14156674350`；锁更新提交 `c378687` |
| 2026-11-15 | T21.7.4 conditional license approval and project LICENSE | 项目 owner 批准有条件接受 `tqdm==4.70.1` 的精确许可证表达式 `MPL-2.0 AND MIT`；配置责任人 `repository owner (rexyll)`、批准日期 2026-11-15、到期/复审日期 2027-02-13、再分发 notice 与 MPL 源码义务。策略执行器仅允许精确 package/version/expression/classification 匹配，保留 `RECIPROCAL` 原始分类并单独审计例外应用；未知许可证、过期例外、版本/表达式不匹配继续 fail-closed。新增根目录 PolyForm Small Business 1.0.0 `LICENSE`、`THIRD_PARTY_NOTICES.md`，README 与供应链设计文档说明小企业商用门槛及第三方许可边界。新增测试覆盖精确匹配、表达式/版本错配与过期。依赖扫描 run `43706969720` 与主 CI run `43706969697` 均通过；全量回归 2,530 passed / 10 skipped，安全回归 237 passed / 9 skipped，Windows smoke 与 coverage job 成功。 | policy `322893e`；evaluator `6f1e4e9`；tests `cd2c61b` / `97c13c6` / `fa99d2a`；LICENSE `21028a4`；notices `40a0da4`；README `8e2a451`（后续个人用途边界同步）；design doc `29b1bd2`（后续扫描结果同步）；scan artifact `14159420157` |

| 2026-11-15 | T21.7.4 dependency/license gate completed | 最新扫描 run `43706969720`（commit `6f1e4e9`）成功：production Linux Py3.14 lock 17/17 包，pip-audit 0 vulnerabilities，OSV freshness 通过（age 6,352s，max 24h，latest advisory `MAL-2026-19942`），Trivy 0.76.2 license policy passed；四项 status exit code 均为 0。扫描 artifact `14159420157` 明确记录唯一 `exception_applied=true` 项为 `tqdm==4.70.1` / `MPL-2.0 AND MIT` / `RECIPROCAL`，批准责任人 `repository owner (rexyll)`，批准日期 2026-11-15，到期/复审 2027-02-13，通知与 MPL 源码义务随报告保留。策略只放行精确 package/version/expression/classification，未知许可证、过期例外和其他 reciprocal 项仍阻断。主 CI run `43706969697` 同一提交全绿：2,530 passed / 10 skipped，安全回归 237 passed / 9 skipped，Windows smoke、coverage job 均成功。T21.7.4 完成；T21.7.3 固定硬件绝对性能预算仍待受控 runner，因此 T21.7 整体仍未完成。 | [Dependency security run](https://github.com/rexyll/AI-Team/actions/runs/43706969720)；artifact `14159420157`；[main CI](https://github.com/rexyll/AI-Team/actions/runs/43706969697)；实现提交 `158241c`、`310df5c`、`63caa04`、`577925c`、`3a93671`、`fac6a20`、`85e82e7`、`6f1e4e9` |


### T21.7.5 项目许可范围修订（2026-11-15）

- **用户确认的产品授权目标**：任何个人均可免费进行非商业使用；符合条件的小企业可在 PolyForm Small Business 1.0.0 的全部条件下进行许可范围内的商业使用；未被 PolyForm Noncommercial 1.0.0 或 PolyForm Small Business 1.0.0 授权的商业用途须事先取得单独书面许可。
- 更新根目录 `LICENSE` 为两份官方 PolyForm 许可证构成的双许可方案。Noncommercial 路径采用官方 PolyForm Noncommercial 1.0.0 原文，允许任何非商业目的，并明确包含个人研究、实验、学习、私人娱乐、爱好和业余活动；该许可不授权商业用途。Small Business 路径采用官方 PolyForm Small Business 1.0.0 原文，完整适用其全部资格门槛与条件；其他商业用途须取得单独书面许可。
- README 与本设计文档已同步说明两条官方许可路径及适用边界；两份 PolyForm 许可证均为原版文本，项目许可证不改变第三方依赖许可。
- 保留 `THIRD_PARTY_NOTICES.md` 对 `tqdm==4.70.1` 的 MPL-2.0 AND MIT 归属与再分发义务；项目许可不能覆盖第三方组件。
- 验收复核与修复（2026-11-15）：一致性检查发现根目录 `LICENSE` 的双许可说明与正文不一致——此前文件只有 PolyForm Noncommercial 1.0.0 正文，Small Business 1.0.0 仅出现在说明段落。已补齐官方 Small Business 1.0.0 完整条款，并补入 Noncommercial Notices 的示例通知；复核两份许可证分别具备完整的 Acceptance、Copyright/Distribution、Notices、Changes、Patent、Fair Use/Small Business、No Other Rights、Patent Defense、Violations、No Liability 和 Definitions 章节。新增 `tests/test_license_contract.py`，锁定两份许可证文本完整性、Noncommercial 授权范围、Small Business 人数/收入门槛、README 双路径说明及第三方依赖许可边界。


**T21.7.5 许可实现与最终验收（2026-11-15）**：最终采用两份原版官方 PolyForm 许可证：非商业用途选择 PolyForm Noncommercial 1.0.0；符合条件的小企业商业用途选择 PolyForm Small Business 1.0.0；未被这两份许可证授权的商业用途须另行取得书面授权。根目录 `LICENSE` 同时附两份官方文本，README 与设计文档同步说明授权边界；第三方依赖继续受其自身许可约束。验收提交：LICENSE `47e2de8`、契约测试 `f9d60ec`，测试空白规范化修复 `548c94b`。最终 main CI #478（run `43709746003`，commit `548c94ba5d8378f02255d4553406aba4d6ad5844`）全部成功：全量回归 2,532 passed / 10 skipped；安全回归 237 passed / 9 skipped；Coverage baseline 2,512 passed / 10 skipped，所有模块行/分支覆盖率底线通过；Windows toolchain smoke 1 passed。T21.7.5 验收完成。T21.7.3 固定硬件绝对性能预算仍因缺少受控 runner 而未完成，因此 T21.7 整体保持未完成。官方文本：https://polyformproject.org/licenses/noncommercial/1.0.0 与 https://polyformproject.org/licenses/small-business/1.0.0 。
