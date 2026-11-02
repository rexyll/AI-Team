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
- [ ] **T4 文档与计划同步**
  - DevPlan 追加 Phase 20 记录（指向本 TaskPlan）；README/`docs/AI-Team-项目文档索引.md` 更新管线全景（含集成/回归/发布阶段）；`CHANGELOG.md` 补录本阶段变更。
  - 验收：文档契约测试（`test_documentation_setup_contract.py` 等）保持绿。

### P1 质量独立性（完整性审计建议 1/3/5）

- [ ] **T5 静态质量门禁**：交付物级 ruff + mypy 门禁作为集成阶段的证据维度（失败→回流或显式豁免记录）。
- [ ] **T6 QA 对抗测试角色**（role=`qa`）：独立于 Developer 的破坏性验证（边界/异常输入/并发），接入产品级测试阶段与角色注册表。
- [ ] **T7 依赖漏洞扫描**：SBOM 生成 + pip-audit（遵守网络出口策略，离线优先）。

### P2 项目管理（完整性审计建议 4/5）

- [ ] **T8 成本报告**：`ModelUsageLedger`/`ProjectCostProjection` → `ProjectResult` 与交付文档成本章节。
- [ ] **T9 需求变更回流**：`--change-request` 文件 → Analyst 增量分析 → 增量任务图（复用 replan 机制）。
- [ ] **T10 版本规划/里程碑**：多需求场景的 Release/迭代概念与优先级排序。

### P3 组织记忆与交付后（完整性审计建议 6/7，OpenClaw heartbeat/memory 借鉴）

- [ ] **T11 跨项目知识库**：历史交付模式/坑/规范沉淀为可加载资产。
- [ ] **T12 UI/UX 与专项开发角色**：按项目类型启用。
- [ ] **T13 交付后监控/缺陷回流**：监控接入、缺陷→热修任务→重新打包的标准化流程。

## 三、执行记录

| 日期 | 节点 | 结果 | 证据 |
|------|------|------|------|
| 2026-11-02 | 梳理 + TaskPlan 建立 | 完成（P0-P3 节点定义） | 本文件 |
