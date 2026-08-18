from agents.base import BaseAgent
from config.model import ask_ai
from runtime.task import Task
from runtime.agent_result import AgentResult

SYSTEM_PROMPT = """
你是一名专业的软件代码 Reviewer。

你的职责：

1. 检查 Developer 的实现
2. 检查是否满足任务要求
3. 检查是否符合 Architect 的设计
4. 检查代码质量
5. 检查测试情况
6. 找出明显问题
7. 决定是否通过

你不能直接修改代码。

审核结果必须严格使用以下格式：

APPROVED

或者：

REVISION_REQUIRED

并说明具体原因。
"""


class ReviewerAgent(BaseAgent):

    @property
    def role(self) -> str:
        return "reviewer"

    def run(self, task: Task):

        if not isinstance(task, Task):
            raise TypeError(
                "ReviewerAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )

        prompt = f"""
        请审核下面的开发任务。

        ====================
        TASK
        ====================

        Task ID:
        {task.id}

        Title:
        {task.title}

        Description:
        {task.description}

        ====================
        DEVELOPER RESULT
        ====================

        {task.result}

        ====================
        UPSTREAM CONTEXT
        ====================

        {task.context}

        ====================
        REVIEW REQUIREMENTS
        ====================

        请检查：

        1. 是否完成任务要求
        2. 是否符合 Architect 设计
        3. 是否存在明显代码问题
        4. 是否有测试证据
        5. 是否存在安全问题
        6. 是否存在明显遗漏

        最终必须给出：

        APPROVED

        或者：

        REVISION_REQUIRED

        并说明原因。
        """

        result = ask_ai(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
        )

        decision = self._parse_review_result(result)

        return AgentResult(
            status=decision,
            agent=self.role,
            task_id=task.id,
            message=result,
        )
        
        
    def _parse_review_result(self, result: str) -> str:

        text = result.strip().upper()

        if text.startswith("REVISION_REQUIRED"):
            return "revision"

        if text.startswith("APPROVED"):
            return "approved"

        raise ValueError(
            "Reviewer returned invalid decision. "
            "Expected APPROVED or REVISION_REQUIRED."
        )
        