# AI-Team 项目文档索引

本目录新增的文档以 `main` 分支源码为事实基准，适用于架构理解、部署、使用和二次开发。

## 文档

1. **[AI-Team-详细设计说明书](./AI-Team-详细设计说明书.md)**
   - 总体架构
   - 分层设计
   - Agent 设计
   - Task 状态机
   - DAG 调度
   - Workflow
   - LLM/Provider
   - Tool Calling
   - Security Sandbox
   - Event Persistence
   - Project Persistence
   - Recovery
   - Retry
   - Concurrency
   - 接口和设计边界

2. **[AI-Team-架构图与流程图](./AI-Team-架构图与流程图.md)**
   - 完整逻辑架构图
   - 项目执行时序图
   - 依赖调度流程图
   - Developer 工具调用流程图
   - 质量门禁流程图
   - 状态机图
   - 持久化架构图
   - 恢复流程图
   - 安全边界图

3. **[AI-Team-接口与实现参考](./AI-Team-接口与实现参考.md)**
   - CLI
   - ProjectOrchestrator
   - Orchestrator
   - TaskManager
   - AgentRouter
   - BaseAgent
   - Agent Result
   - Developer/Tester/Reviewer
   - BaseLLM/ProviderLLM
   - ToolRegistry/ToolGuard
   - WorkspaceSandbox
   - WorkflowEvent/EventPersistence
   - ProjectPersistence
   - Configuration

4. **[AI-Team-部署运维手册](./AI-Team-部署运维手册.md)**
   - Windows 11 + Python 3.14 环境
   - venv
   - 依赖安装
   - Provider 配置
   - 启动
   - Workspace
   - 参数
   - 持久化部署
   - 恢复
   - 审计
   - 故障排查
   - 发布检查

5. **[AI-Team-用户使用手册](./AI-Team-用户使用手册.md)**
   - 第一次使用
   - 需求编写
   - Agent 职责
   - 工作区
   - 状态解释
   - Tester/Reviewer 返工
   - 多模型
   - 常见错误
   - 最佳实践

## 原有文档

- `README.md`：项目简介与快速开始
- `docs/setup.md`：当前 canonical setup/runtime guide
- `docs/user_guide.md`：原有真实 Provider 使用说明
- `docs/production_configuration.md`：生产配置契约
- `docs/release_readiness.md`：release readiness
- `DevPlan.md`：开发与验收历史

## 文档基准说明

逆向文档主要根据以下源码边界整理：

- `main.py`
- `agents/`
- `core/`
- `runtime/`
- `config/`
- `tools/`
- `security/`
- `integration/`
- `tests/`

如果实现继续变化，建议下一次开发节点同时更新源码、契约测试和本文档。
