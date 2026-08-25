from __future__ import annotations

import json
import os
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

硬性格式要求（违反会导致判定无效）：

1. 输出的第一行必须只包含英文单词 APPROVED 或 REVISION_REQUIRED，
   不要加粗、不要编号、不要附加任何其他文字或标点；
2. 判定必须以该英文标记表达——禁止仅用中文"通过/需返工"表述结论；
3. 原因说明放在后续行，可使用中文。
"""


DEFAULT_REVIEWER_MAX_DEVELOPER_RESULT_CHARS = 16000


def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _truncate_text(value: Any, limit: int) -> str:
    """Render a value for the reviewer without allowing unbounded prompt growth."""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text

    marker = f"\n...[truncated {len(text) - limit} chars]...\n"
    if len(marker) >= limit:
        return text[:limit]

    head = (limit - len(marker)) // 2
    tail = limit - len(marker) - head
    return text[:head] + marker + text[-tail:]


def _compact_developer_result(result: Any, limit: int) -> str:
    """Keep review evidence while bounding large code/report payloads.

    Developer results can contain complete test files or long command output.
    The reviewer still receives the canonical metadata and high-value evidence
    fields first; verbose report/code text is bounded with a head/tail marker.
    """
    if not isinstance(result, dict):
        return _truncate_text(result, limit)

    compact: dict[str, Any] = {}
    for key in ("status", "agent", "task_id"):
        if key in result:
            compact[key] = result[key]

    message = result.get("message")
    if message:
        compact["message"] = _truncate_text(message, min(2000, limit))

    data = result.get("data")
    if isinstance(data, dict):
        compact_data: dict[str, Any] = {}

        # Preserve objective evidence ahead of verbose free-form reports.
        for key in ("files_changed", "tests", "validation", "summary"):
            if key in data:
                compact_data[key] = data[key]

        for key in ("implementation", "architecture", "report"):
            if key in data:
                compact_data[key] = _truncate_text(
                    data[key],
                    min(6000, max(1000, limit // 3)),
                )

        for key, value in data.items():
            if key not in compact_data:
                compact_data[key] = _truncate_text(
                    value,
                    min(2000, max(500, limit // 8)),
                )

        compact["data"] = compact_data
    elif "data" in result:
        compact["data"] = _truncate_text(result["data"], min(4000, limit))

    return _truncate_text(
        json.dumps(compact, ensure_ascii=False, indent=2, default=str),
        limit,
    )


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
        developer_result = _compact_developer_result(
            view["task_result"],
            _positive_env_int(
                "REVIEWER_MAX_DEVELOPER_RESULT_CHARS",
                DEFAULT_REVIEWER_MAX_DEVELOPER_RESULT_CHARS,
            ),
        )
        tester_feedback = _truncate_text(view["tester_feedback"], 8000)
        reviewer_feedback = _truncate_text(view["reviewer_feedback"], 6000)
        dependency_context = _truncate_text(view["dependency_context"], 8000)
        history = _truncate_text(view["history"], 4000)
        metadata = _truncate_text(view["metadata"], 4000)

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
DEVELOPER RESULT (BOUNDED)
====================

{developer_result}

====================
TESTER RESULT
====================

{tester_feedback}

====================
PREVIOUS REVIEW RESULT
====================

{reviewer_feedback}

====================
UPSTREAM CONTEXT
====================

{dependency_context}

====================
EXECUTION CONTEXT
====================

history={history}
metadata={metadata}
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
- DEVELOPER RESULT 可能因为上下文预算而被截断；截断标记表示省略了
  非核心的长文本，不代表测试证据本身被删除。应优先依据 files_changed、tests、
  validation、Tester 结论以及任务要求做判断。

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

        response_head = text.replace("\n", " ")[:200]
        raise ValueError(
            "Reviewer returned invalid decision. "
            "Expected APPROVED or REVISION_REQUIRED. "
            f"Response head: {response_head!r}"
        )
