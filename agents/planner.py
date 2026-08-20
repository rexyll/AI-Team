from __future__ import annotations

import json
from typing import Any

from config.model import ask_ai
from runtime.task_validator import validate_plan
from agents.base import BaseAgent
from runtime.task import Task



SYSTEM_PROMPT = """
你是一名专业的软件项目规划师（Planner）。

你的职责是：

1. 理解用户的软件开发需求
2. 将需求拆分成清晰、可执行的开发任务
3. 为每个任务指定负责角色
4. 确定任务之间的依赖关系

你不能编写代码。
你不能修改文件。
你不能执行命令。

允许使用的角色：

- architect
- developer
- tester
- reviewer

必须输出一个 JSON 对象。

JSON 格式：

{
    "project": "项目名称",
    "summary": "项目摘要",
    "tasks": [
        {
            "id": "TASK-001",
            "title": "任务名称",
            "description": "任务详细描述",
            "role": "architect",
            "dependencies": []
        }
    ]
}

严格规则：

1. project 必须是非空字符串。
2. summary 必须是非空字符串。
3. tasks 必须是非空数组。
4. 每个 task 必须包含：
   - id
   - title
   - description
   - role
   - dependencies
5. task id 必须唯一。
6. role 只能是 architect、developer、tester、reviewer。
7. dependencies 必须是 task id 数组。
8. dependencies 只能引用当前计划中存在的 task id。
9. 不允许任务依赖自己。
10. 不允许出现循环依赖。
11. 不允许增加 JSON 格式之外的字段。
12. 只输出 JSON，不要输出解释文字。
13. 不要输出 Markdown。
14. 不要输出 ```json。
"""

MAX_PLAN_RETRIES = 2

def _extract_json_object(response: str) -> str:
    """
    Extract the first complete JSON object from an LLM response.

    Supported responses include:

        {"project": "...", ...}

    and:

        ```json
        {"project": "...", ...}
        ```

    and:

        Here is the plan:
        {"project": "...", ...}

    The function intentionally extracts only a JSON object and does
    not attempt to repair malformed JSON.
    """
    response = response.strip()

    if not response:
        raise ValueError(
            "Planner 返回了空响应。"
        )

    # Fast path: response is already a complete JSON value.
    #
    # We intentionally preserve a top-level JSON array here instead
    # of extracting the first object from it. The parser layer will
    # then reject it with the correct "root must be an object" error.
    if (
        response.startswith("{")
        and response.endswith("}")
    ):
        return response

    if (
        response.startswith("[")
        and response.endswith("]")
    ):
        return response

    # Remove Markdown code fences when present.
    if "```" in response:
        blocks = response.split("```")

        for block in blocks:
            candidate = block.strip()

            if candidate.startswith("json"):
                candidate = candidate[4:].strip()

            if candidate.startswith("{") and candidate.endswith("}"):
                return candidate

    # Locate the first JSON object embedded in normal text.
    start = response.find("{")

    if start == -1:
        raise ValueError(
            "Planner 返回内容中没有找到 JSON 对象。"
        )

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(response)):
        char = response[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return response[start:index + 1]

    raise ValueError(
        "Planner 返回内容包含不完整的 JSON 对象。"
    )


def _parse_plan_response(response: str) -> dict[str, Any]:
    """
    Extract, parse, and validate a Planner response.

    Raises:
        ValueError:
            If the response is empty, does not contain valid JSON,
            has a non-object JSON root, or violates the plan schema.
    """
    response = response.strip()

    if not response:
        raise ValueError("Planner 返回为空响应")

    response = _extract_json_object(response)

    try:
        plan = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Planner 返回的内容不是合法 JSON。\n"
            f"原始响应：\n{response}"
        ) from exc

    if not isinstance(plan, dict):
        raise ValueError("根节点必须是对象")

    validate_plan(plan)

    return plan

def _build_repair_prompt(
    requirement: str,
    invalid_response: str,
    error: Exception,
) -> str:
    return f"""
    上一轮 Planner 输出无法通过验证。

    原始需求：

    {requirement}

    上一轮输出：

    {invalid_response}

    验证错误：

    {error}

    请重新生成一个合法的项目开发计划。

    要求：

    1. 必须输出 JSON Object。
    2. 不允许输出 Markdown。
    3. 不允许输出 ```json。
    4. 必须包含 project。
    5. 必须包含 summary。
    6. 必须包含 tasks。
    7. 每个 task 必须包含：
    - id
    - title
    - description
    - role
    - dependencies
    8. role 必须是：
    - architect
    - developer
    - tester
    - reviewer
    9. task id 必须唯一。
    10. dependencies 只能引用存在的 task id。
    11. 不允许循环依赖。
    12. 不允许重复 dependency。
    13. 不要输出 JSON 之外的内容。

    请只输出最终 JSON。
    """

def create_plan(requirement: str) -> dict:
    prompt = f"""
请根据下面的软件需求制定开发计划：

{requirement}
"""

    last_error: Exception | None = None
    last_response = ""

    for attempt in range(MAX_PLAN_RETRIES + 1):
        if attempt == 0:
            current_prompt = prompt
        else:
            current_prompt = _build_repair_prompt(
                requirement=requirement,
                invalid_response=last_response,
                error=last_error,
            )

        response = ask_ai(
            prompt=current_prompt,
            system_prompt=SYSTEM_PROMPT,
        )

        last_response = response

        try:
            return _parse_plan_response(response)

        except ValueError as exc:
            last_error = exc

            if attempt >= MAX_PLAN_RETRIES:
                raise ValueError(
                    "Planner 在多次尝试后仍无法生成合法计划。\n"
                    f"最后一次错误：{exc}"
                ) from exc

    raise RuntimeError("Planner retry loop exited unexpectedly")


class PlannerAgent(BaseAgent):

    @property
    def role(self) -> str:
        return "planner"

    def run(self, task: Task):
        if not isinstance(task, Task):
            raise TypeError(
                "PlannerAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )

        plan = create_plan(task.description)

        return {
            "status": "planner_completed",
            "agent": self.role,
            "task_id": task.id,
            "plan": plan,
        }