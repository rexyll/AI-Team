from agents.base import BaseAgent
from config.model import ask_ai
from runtime.agent_context import AgentContext
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

    def _build_messages(
        self,
        context: AgentContext,
    ) -> list[dict[str, str]]:
        prompt = f"""
请分析下面的软件开发任务，并给出架构设计。

====================
TASK CONTEXT
====================

任务 ID：
{context.task_id}

任务名称：
{context.task_title}

任务描述：
{context.task_description}

Agent Role：
{context.role}

当前状态：
{context.status}

任务依赖：
{context.dependencies}

当前任务已有结果：
{context.task_result}

Tester Feedback：
{context.tester_feedback}

Reviewer Feedback：
{context.reviewer_feedback}

Review Round：
{context.review_round}

Execution History：
{context.history}

Metadata：
{context.metadata}

====================
ARCHITECTURE REQUIREMENTS
====================

请给出完整的架构设计，包括：

1. 任务分析
2. 架构方案
3. 数据模型
4. 模块设计
5. 接口设计
6. 关键技术决策
7. 潜在风险
8. 实施建议

请优先复用现有项目架构，避免无必要的复杂设计。

不要编写具体业务代码。
不要修改任何文件。
"""

        return [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

    def run(self, task: Task) -> AgentResult:
        if not isinstance(task, Task):
            raise TypeError(
                "ArchitectAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )

        context = self.build_context(task)

        messages = self._build_messages(context)

        prompt = messages[1]["content"]

        result = ask_ai(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
        )

        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=context.task_id,
            message=result,
            data={
                "architecture": result,
            },
        )