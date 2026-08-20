from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from config.model import ask_ai
from runtime.agent_result import AgentResult
from runtime.task import Task


SYSTEM_PROMPT = """
你是一名专业的软件代码 Reviewer。

你的职责：

1. 检查 Developer 的实现
2. 检查是否满足任务要求
3. 检查是否符合 Architect 的设计
4. 检查代码质量
5. 检查测试情况
6. 检查 Tester 的测试结论
7. 检查安全问题
8. 找出明显问题
9. 决定是否通过

你不能直接修改代码。

你必须区分：

- Developer 的开发报告
- Developer 的实际测试证据
- Tester 的测试结论
- Reviewer 自己的审核判断

不能把 Developer 的主观描述当成事实证据。

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

    def run(self, task: Task) -> AgentResult:
        if not isinstance(task, Task):
            raise TypeError(
                "ReviewerAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )

        prompt = self._build_prompt(task)

        result = ask_ai(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
        )

        decision = self._parse_review_result(result)

        data = self._build_result_data(
            content=result,
            decision=decision,
            task=task,
        )

        return AgentResult(
            status=decision,
            agent=self.role,
            task_id=task.id,
            message=result,
            data=data,
        )

    @staticmethod
    def _build_prompt(task: Task) -> str:
        developer_result = ReviewerAgent._extract_task_result(
            task.result
        )

        tester_result = ReviewerAgent._extract_feedback(
            task.test_result
        )

        reviewer_feedback = ReviewerAgent._extract_feedback(
            task.review_result
        )

        return f"""
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

{developer_result}

====================
TESTER RESULT
====================

{tester_result}

====================
PREVIOUS REVIEW RESULT
====================

{reviewer_feedback}

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
4. 是否有实际测试证据
5. Tester 的结论是否合理
6. 是否存在安全问题
7. 是否存在明显遗漏
8. 是否存在未完成内容
9. 是否需要 Developer 返工

特别注意：

- Developer 的 summary/report 不是测试证据。
- Developer 的 files_changed 只能说明修改范围。
- Developer 的 tests 才是主要测试证据之一。
- Tester 的结果必须纳入审核判断。
- 如果 Tester FAILED，通常不应该 APPROVED。
- 如果 Tester PASSED，也必须检查 Developer 是否真正满足任务要求。
- 不要声称执行了没有执行的测试。
- 不要修改代码。

最终必须给出：

APPROVED

或者：

REVISION_REQUIRED

并说明具体原因。
"""

    @staticmethod
    def _extract_task_result(
        result: Any,
    ) -> Any:
        """
        Convert AgentResult / dict / legacy value into a representation
        suitable for the Reviewer prompt.
        """

        if isinstance(result, AgentResult):
            return result.to_dict()

        if isinstance(result, dict):
            return result

        return result

    @staticmethod
    def _extract_feedback(
        result: Any,
    ) -> Any:
        """
        Extract feedback/result while preserving compatibility with
        both AgentResult and legacy dictionaries.
        """

        if isinstance(result, AgentResult):
            return result.to_dict()

        if isinstance(result, dict):
            return dict(result)

        if result is None:
            return {}

        return result

    @staticmethod
    def _build_result_data(
        *,
        content: str,
        decision: str,
        task: Task,
    ) -> dict[str, Any]:
        """
        Build the structured Reviewer Result payload.

        The Reviewer records the evidence it actually received rather
        than inventing additional facts.
        """

        developer_result = ReviewerAgent._extract_task_result(
            task.result
        )

        tester_result = ReviewerAgent._extract_feedback(
            task.test_result
        )

        developer_data: dict[str, Any] = {}

        if isinstance(developer_result, AgentResult):
            developer_data = dict(
                developer_result.data
            )

        elif isinstance(developer_result, dict):
            data = developer_result.get(
                "data",
                developer_result,
            )

            if isinstance(data, dict):
                developer_data = dict(data)

        tests = developer_data.get(
            "tests",
            [],
        )

        files_changed = developer_data.get(
            "files_changed",
            [],
        )

        if not isinstance(tests, list):
            tests = []

        if not isinstance(files_changed, list):
            files_changed = []

        tester_status = None

        if isinstance(tester_result, AgentResult):
            tester_status = tester_result.status

        elif isinstance(tester_result, dict):
            tester_status = tester_result.get(
                "status"
            )

        return {
            "summary": content.strip(),
            "decision": decision,
            "tester_status": tester_status,
            "files_changed": list(files_changed),
            "tests": list(tests),
            "validation": {
                "test_evidence_count": len(tests),
                "files_changed_count": len(files_changed),
                "tester_result_available": bool(
                    tester_result
                ),
            },
            "report": content,
        }

    @staticmethod
    def _parse_review_result(
        result: str,
    ) -> str:
        if not isinstance(result, str):
            raise ValueError(
                "Reviewer returned invalid decision. "
                "Expected APPROVED or REVISION_REQUIRED."
            )

        text = result.strip().upper()

        if text.startswith("REVISION_REQUIRED"):
            return "revision"

        if text.startswith("APPROVED"):
            return "approved"

        raise ValueError(
            "Reviewer returned invalid decision. "
            "Expected APPROVED or REVISION_REQUIRED."
        )
