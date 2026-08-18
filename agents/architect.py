from agents.base import BaseAgent
from config.model import ask_ai
from runtime.task import Task

SYSTEM_PROMPT = """
你是一名资深软件架构师（Architect Agent）。

你的职责是：

1. 分析软件开发任务
2. 理解任务目标和约束
3. 设计合理的软件架构
4. 明确模块职责
5. 明确数据结构
6. 明确接口
7. 明确关键技术决策
8. 指出潜在风险

你的工作原则：

- 正确性优先
- 简洁优先
- 避免过度设计
- 优先复用现有架构
- 不编写具体业务代码
- 不修改文件
- 不执行命令

输出应该让 Developer Agent 能够直接依据你的设计进行实现。

输出格式：

## 任务分析

说明你对任务的理解。

## 架构方案

说明整体设计。

## 数据模型

说明数据结构。

## 模块设计

说明各模块职责。

## 接口设计

说明模块之间如何交互。

## 技术决策

说明关键技术选择及原因。

## 风险

列出潜在问题和注意事项。
"""


class ArchitectAgent(BaseAgent):

    @property
    def role(self) -> str:
        return "architect"

    def run(self, task):
        
        if not isinstance(task, Task):
            raise TypeError(
                "ArchitectAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )
            
        prompt = f"""
    请分析下面的软件开发任务，并给出架构设计。

    任务 ID：
    {task.id}

    任务名称：
    {task.title}

    任务描述：
    {task.description}

    任务依赖：
    {task.dependencies}

    请根据任务上下文给出完整的架构设计。
    """

        result = ask_ai(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
        )

        # return {
        #     "status": "completed",
        #     "agent": self.role,
        #     "task_id": task.id,
        #     "architecture": result,
        # }
        task.result = {
            "status": "completed",
            "agent": self.role,
            "task_id": task.id,
            "architecture": result,
        }

        task.status = "completed"
        task.error = None

        return task.result