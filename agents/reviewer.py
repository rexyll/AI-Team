from __future__ import annotations

from typing import Any

from agents.base import BaseAgent

from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.context_view import context_view
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
9. 检查交付物的可运行性：Developer 报告的启动命令是否明确，
   该命令在包结构下是否真实可行（例如使用了相对导入的模块必须以
   python -m 方式运行，不能要求用户直接执行裸脚本）
10. 决定是否通过

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

输出的第一行必须只包含 APPROVED 或 REVISION_REQUIRED 这两个词之一，
不要加粗、不要编号、不要附加任何其他文字；原因说明放在后续行。
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

        context = self.build_context(task)
        prompt = self._build_prompt(context)

        result = self.llm.generate(
            prompt,
            system_prompt=SYSTEM_PROMPT,
        )

        decision = self._parse_review_result(result)

        data = self._build_result_data(
            content=result,
            decision=decision,
            context=context,
        )

        return AgentResult(
            status=decision,
            agent=self.role,
            task_id=context.task_id,
            message=result,
            data=data,
        )

    @staticmethod
    def _build_prompt(context: AgentContext) -> str:
        view = context_view(context, "reviewer")

        return f"""
请审核下面的开发任务。

====================
TASK
====================

Task ID:
{view['task_id']}

Title:
{view['task_title']}

Description:
{view['task_description']}

====================
DEVELOPER RESULT
====================

{view['task_result']}

====================
TESTER RESULT
====================

{view['tester_feedback']}

====================
PREVIOUS REVIEW RESULT
====================

{view['reviewer_feedback']}

====================
UPSTREAM CONTEXT
====================

{view['dependency_context']}

====================
EXECUTION CONTEXT
====================

history={view['history']}
metadata={view['metadata']}
review_round={view['review_round']}

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
    def _build_result_data(
        *,
        content: str,
        decision: str,
        context: AgentContext,
    ) -> dict[str, Any]:
        developer_result = context.task_result
        tester_result = context.tester_feedback

        developer_data: dict[str, Any] = {}

        if isinstance(developer_result, dict):
            data = developer_result.get("data", developer_result)
            if isinstance(data, dict):
                developer_data = dict(data)

        tests = developer_data.get("tests", [])
        files_changed = developer_data.get("files_changed", [])

        if not isinstance(tests, list):
            tests = []
        if not isinstance(files_changed, list):
            files_changed = []

        tester_status = None
        if isinstance(tester_result, dict):
            tester_status = tester_result.get("status")

        return {
            "summary": content.strip(),
            "decision": decision,
            "tester_status": tester_status,
            "files_changed": list(files_changed),
            "tests": list(tests),
            "validation": {
                "test_evidence_count": len(tests),
                "files_changed_count": len(files_changed),
                "tester_result_available": bool(tester_result),
            },
            "report": content,
        }

    @staticmethod
    def _parse_review_result(result: str) -> str:
        if not isinstance(result, str):
            raise ValueError(
                "Reviewer returned invalid decision. "
                "Expected APPROVED or REVISION_REQUIRED."
            )

        text = result.strip().upper()

        # Fast path: verdict-first responses (the documented contract).
        if text.startswith("REVISION_REQUIRED"):
            return "revision"

        if text.startswith("APPROVED"):
            return "approved"

        # Real models frequently reason first and state the verdict later,
        # or wrap it in markdown. Scan the whole response for the verdict
        # tokens. A revision signal anywhere wins: an approval gate must
        # stay conservative on ambiguous evidence (deny-by-default).
        if "REVISION_REQUIRED" in text:
            return "revision"

        if "APPROVED" in text:
            return "approved"

        raise ValueError(
            "Reviewer returned invalid decision. "
            "Expected APPROVED or REVISION_REQUIRED."
        )
