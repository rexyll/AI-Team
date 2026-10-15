# 交付能力路线图(End-to-End Delivery Capability Roadmap)

目标状态:把一个客户需求(明确程度不确定——可能带完整功能清单与验收指标,也可能只有一句话)交给团队,团队自主交付**最终产品 + 全套文档**(需求文档、设计文档、测试结果文档、部署指引、用户手册)。

## 一、现状结构(已具备)

```text
用户需求(文本)
   ↓ extract_required_paths(路径约束机械注入)
Planner(拆解任务图,architect/developer/tester/reviewer 四类角色)
   ↓ validate_plan
DependencyScheduler → ResourceGovernor → Orchestrator(有界并行)
   ↓ 每任务 TaskWorkflow:Developer(工具循环)→ Tester(判定)→ Reviewer(门禁,守卫重试/返工轮)
ProjectResult + 项目快照持久化 + Workflow 事件溯源(JSON/SQLite) + 制品库(大输出归档)
横向:LLM 治理(预算/熔断/回退)、工具调用边界(权限/审计)、进程沙箱(Job Object)、
     可观测性(日志/指标/追踪/告警/仪表盘)、安全(注入围栏/脱敏/网络出口/依赖策略)
```

已验证:全量回归 1998 passed + 安全回归套件;单/多 Developer 真实供应商实弹交付。

## 二、差距分析(对照交付目标)

| # | 差距 | 现状 | 影响 | 本轮方案 |
|---|------|------|------|----------|
| 1 | 模糊需求无澄清/结构化环节 | 一句话需求直接进 Planner,假设隐式散失 | 交付物偏离客户预期且不可追溯 | 新增需求分析师(Analyst):输出结构化需求规格草案(REQ 编号、优先级、验收标准、显式【假设】、【待确认问题】) |
| 2 | 文档体系缺失 | 只有代码 + README(由 Developer 顺带产出) | 不构成完整交付 | 新增交付文档工程师(DocWriter):产出需求规格说明书/设计文档/测试结果报告/部署指引/用户手册,落盘 `docs/` |
| 3 | 无交付清单与完整性核对 | 交付物边界模糊 | 客户无法核对收货 | 确定性交付清单(文件+大小+sha256,排除运行时杂质)+ 文档存在性核对 |
| 4 | 验收阶段缺失 | Reviewer 只做代码质量审核 | 产品需求符合性无人判定 | (本轮轻量)文档/清单核对;独立 Acceptance 阶段列入后续阶段 |
| 5 | 集成约束 | 核心 Workflow 状态机不可随意扩展 | — | Analyst 为 `create_plan` 前置步,DocWriter+清单为 `execute` 后置步(项目级编排,任务图零改动) |

## 三、本轮落地范围

1. `agents/analyst.py` — RequirementAnalystAgent(role="analyst",纯 LLM,输入围栏)
2. `agents/doc_writer.py` — DocWriterAgent(role="doc_writer",READ+WRITE,无 EXECUTE;按文档逐份生成并经沙箱落盘)
3. `runtime/delivery_manifest.py` — 确定性交付清单
4. `core/project_orchestrator.py` — `create_plan` 前置需求分析;`execute` 后置文档+清单阶段;事件可观测
5. `security/runtime_capability.py` + `runtime/agent_factory.py` — 角色注册
6. `main.py` — 交付目录透传
7. 回归 + mock 全链路测试(真实供应商 E2E 待额度恢复后补跑)

## 四、后续阶段(不在本轮)

- **交互式澄清协议**:Analyst 输出【待确认问题】后暂停,等客户答复再继续(需要会话状态机)
- **独立 Acceptance 阶段**:产品需求符合性验收(与 Reviewer 代码质量分离;optional_plan #17)
- **部署产物**:容器镜像/安装包构建、冒烟验证
- **多轮迭代交付**:客户反馈回流为新的任务图增量
- **文档质量门禁**:对生成文档做一致性校验(需求 ID 追溯矩阵)
