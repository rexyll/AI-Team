from agents.base import BaseAgent
from config.model import ask_ai
from runtime.task import Task
from runtime.agent_result import AgentResult

SYSTEM_PROMPT = """
你是一名专业的软件测试工程师（Tester Agent）。

你的职责是验证 Developer 的实现，而不是修改代码。

你必须：
1. 检查任务要求是否得到实现
2. 检查 Developer 提供的测试证据
3. 分析潜在边界条件、回归风险和错误处理
4. 基于现有测试结果给出测试结论

你不能修改代码，也不能把架构设计当作测试结果。

最终使用以下格式：
TEST_PASSED

或者：
TEST_FAILED
并说明失败原因。
"""


class TesterAgent(BaseAgent):
    @property
    def role(self) -> str:
        return "tester"

    def run(self, task: Task):
        if not isinstance(task, Task):
            raise TypeError(
                "TesterAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )

        prompt = f"""
        请测试下面的软件开发任务。

        ====================
        TASK
        ====================
        Task ID: {task.id}
        Title: {task.title}
        Description: {task.description}

        ====================
        DEVELOPER RESULT
        ====================
        {task.result}

        ====================
        CONTEXT
        ====================
        {task.context}

        请根据已有测试证据分析实现是否满足任务要求。
        不要声称执行了没有证据表明执行过的测试。

        最终必须输出：
        TEST_PASSED
        或
        TEST_FAILED
        并说明原因。
        """

        result = ask_ai(prompt=prompt, system_prompt=SYSTEM_PROMPT)
        decision = self._parse_result(result)

        return AgentResult(
            status=decision,
            agent=self.role,
            task_id=task.id,
            message=result,
        )

    @staticmethod
    def _parse_result(result: str) -> str:
        text = result.strip().upper()
        if text.startswith("TEST_PASSED"):
            return "passed"
        if text.startswith("TEST_FAILED"):
            return "failed"
        raise ValueError(
            "Tester returned invalid decision. "
            "Expected TEST_PASSED or TEST_FAILED."
        )
