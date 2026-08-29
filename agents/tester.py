from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.context_view import context_view
from runtime.provenance import agent_feedback_provenance, provenance_from_value
from runtime.task import Task

SYSTEM_PROMPT = """
你是一名专业的软件测试工程师（Tester Agent）。

你的职责是验证 Developer 的实现，而不是修改代码。

你必须：

1. 检查任务要求是否得到实现
2. 检查 Developer 提供的测试证据
3. 分析潜在边界条件、回归风险和错误处理
4. 基于已有测试证据给出测试结论
5. 明确区分“已有证据”和“推测”
6. 不得声称执行了没有证据表明执行过的测试

你不能：

- 修改代码
- 执行代码修改操作
- 把 Architect 的架构设计当作测试结果
- 把 Developer 的主观描述当作测试证据
- 编造测试结果

测试结果必须严格使用以下格式之一：

TEST_PASSED

或者：

TEST_FAILED

并说明具体原因。

硬性格式要求（违反会导致判定无效）：

1. 输出的第一行必须只包含英文单词 TEST_PASSED 或 TEST_FAILED，
   不要加粗、不要编号、不要附加任何其他文字或标点；
2. 判定必须以该英文标记表达——禁止仅用中文"通过/失败"表述结论；
3. 原因说明放在后续行，可使用中文。
"""


class TesterAgent(BaseAgent):
    @property
    def role(self) -> str:
        return "tester"

    def run(self, task: Task) -> AgentResult:
        if not isinstance(task, Task):
            raise TypeError("TesterAgent.run() expects Task, " f"got {type(task).__name__}")
        context = self.build_context(task)
        prompt = self._build_prompt(context)
        result = self._generate(prompt, system_prompt=SYSTEM_PROMPT)
        decision = self._parse_result(result)
        data = self._build_result_data(content=result, decision=decision, context=context)
        return AgentResult(status=decision, agent=self.role, task_id=context.task_id, message=result, data=data)

    @staticmethod
    def _build_prompt(context: AgentContext) -> str:
        view = context_view(context, "tester")
        return f"""
请测试下面的软件开发任务。

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
TESTING REQUIREMENTS
====================

请重点检查：

1. 任务要求是否真正得到实现
2. Developer 是否提供了实际测试证据
3. 测试命令及测试结果是否可信
4. 是否存在明显边界条件问题
5. 是否存在明显回归风险
6. 是否存在错误处理遗漏
7. 是否存在安全问题
8. 是否存在明显未完成内容

特别注意：

- 如果 Developer Result 中存在 tests 字段，请优先检查其中的实际测试命令和结果。
- files_changed 只能作为修改范围证据，不能证明功能正确。
- summary/report 只能作为开发者报告，不能代替测试证据。
- 不要声称自己执行了测试，除非系统明确提供了实际测试执行能力。
- 如果测试证据不足，应明确指出证据不足。
- 不能因为 Developer 声称“测试通过”就自动判定通过。

最终必须输出：

TEST_PASSED

或者：

TEST_FAILED

并说明原因。
"""

    @staticmethod
    def _build_result_data(*, content: str, decision: str, context: AgentContext) -> dict[str, Any]:
        developer_result = context.task_result
        tests: list[Any] = []
        files_changed: list[Any] = []
        if isinstance(developer_result, dict):
            data = developer_result.get("data", developer_result)
            if isinstance(data, dict):
                tests_value = data.get("tests", [])
                if isinstance(tests_value, list):
                    tests = list(tests_value)
                files_value = data.get("files_changed", [])
                if isinstance(files_value, list):
                    files_changed = list(files_value)
        parent = provenance_from_value(developer_result)
        provenance = agent_feedback_provenance(
            task_id=context.task_id,
            agent_role="tester",
            evidence_id=f"tester:{context.task_id}",
            parent_evidence_id=parent.evidence_id if parent else None,
        )
        return {
            "summary": content.strip(),
            "decision": decision,
            "tests": tests,
            "files_changed": files_changed,
            "validation": {"test_evidence_count": len(tests), "files_changed_count": len(files_changed), "evidence_available": bool(tests)},
            "provenance": provenance.to_dict(),
            "report": content,
        }

    @staticmethod
    def _parse_result(result: str) -> str:
        if not isinstance(result, str):
            raise ValueError("Tester returned invalid decision. Expected TEST_PASSED or TEST_FAILED.")
        text = result.strip().upper()
        if text.startswith("TEST_PASSED"):
            return "passed"
        if text.startswith("TEST_FAILED"):
            return "failed"
        if "TEST_FAILED" in text:
            return "failed"
        if "TEST_PASSED" in text:
            return "passed"
        response_head = text.replace("\n", " ")[:200]
        raise ValueError("Tester returned invalid decision. Expected TEST_PASSED or TEST_FAILED. " f"Response head: {response_head!r}")
