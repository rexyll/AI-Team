from agents.base import BaseAgent
from config.model import ask_ai
from runtime.agent_result import AgentResult
from runtime.task import Task


SYSTEM_PROMPT = """
你是一名资深软件架构师（Architect Agent）。

你的职责是：
1. 分析软件开发任务
2. 理解任务目标和约束
3. 设计合理的软件架构
4. 明确模块职责、数据结构和接口
5. 明确关键技术决策
6. 指出潜在风险

你的工作原则：正确性优先、简洁优先、避免过度设计、优先复用现有架构。
你不编写具体业务代码、不修改文件、不执行命令。
"""


class ArchitectAgent(BaseAgent):

    @property
    def role(self) -> str:
        return "architect"

    def run(self, task: Task) -> AgentResult:
        if not isinstance(task, Task):
            raise TypeError(
                "ArchitectAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )

        prompt = f"""
请分析下面的软件开发任务，并给出架构设计。

任务 ID：{task.id}
任务名称：{task.title}
任务描述：{task.description}
任务依赖：{task.dependencies}

请给出完整的架构设计，包括任务分析、架构方案、数据模型、模块设计、接口设计、技术决策和风险。
"""

        result = ask_ai(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
        )

        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=task.id,
            message=result,
            data={
                "architecture": result,
            },
        )