from __future__ import annotations

import json
from typing import Any

from config.model import ask_ai
from runtime.llm.base import BaseLLM
from runtime.plan_constraints import apply_path_constraints, extract_required_paths
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

用户需求中的显式约束必须逐条落实：

- 需求中指定的输出目录、文件路径、命名、技术栈、阶段顺序等约束，
  必须原样写入相关任务的 description 中，不得省略或改写。
- 执行者应能仅凭任务 description 就遵守全部约束，
  因此与目录/路径相关的约束要写入第一个实现类任务的 description。
- 拆解完成后自检一遍：逐条核对需求原文，确认没有遗漏任何显式约束。

各角色的职责边界（分配任务时必须遵守）：

- architect：设计结构与接口规范，不产出业务代码。
- developer：编写代码、编写测试用例、运行验证命令、修复问题。
  "编写单元测试"类任务属于 developer。
- tester：审查 Developer 提交的测试证据并给出 TEST_PASSED / TEST_FAILED
  判定。tester 不编写代码、不编写测试文件、不执行命令，
  因此不要给 tester 安排"编写测试"或"运行测试"类任务。
- reviewer：最终审核并判定 APPROVED / REVISION_REQUIRED。
  reviewer 不执行修复；审核不通过时通过返工循环交还 developer。

参考拆解模板（按项目规模裁剪，不要求照搬）：

架构设计(architect) → 功能实现(developer) → 测试用例编写(developer) →
测试证据审查(tester) → 最终审核(reviewer)

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

def create_plan(requirement: str, *, llm: BaseLLM | None = None) -> dict:
    """Create a validated plan for ``requirement``.

    When ``llm`` is provided, all completions route through the injected
    :class:`BaseLLM` (constructor-injection contract). When omitted, the
    legacy module-level provider entry point is used so existing callers
    and monkeypatch-based tests keep working unchanged.
    """

    if llm is not None and not isinstance(llm, BaseLLM):
        raise TypeError("create_plan llm must implement BaseLLM")

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

        if llm is not None:
            response = llm.generate(
                current_prompt,
                system_prompt=SYSTEM_PROMPT,
            )
        else:
            response = ask_ai(
                prompt=current_prompt,
                system_prompt=SYSTEM_PROMPT,
            )

        last_response = response

        try:
            plan = _parse_plan_response(response)
            return _enforce_requirement_paths(requirement, plan)

        except ValueError as exc:
            last_error = exc

            if attempt >= MAX_PLAN_RETRIES:
                raise ValueError(
                    "Planner 在多次尝试后仍无法生成合法计划。\n"
                    f"最后一次错误：{exc}"
                ) from exc

    raise RuntimeError("Planner retry loop exited unexpectedly")


def _enforce_requirement_paths(requirement: str, plan: dict) -> dict:
    """Mechanically enforce requirement-level path constraints on the plan.

    Prompt guidance alone proved insufficient across three real-provider
    runs (plans kept dropping the mandated output directory). This step
    deterministically injects any missing directory constraint into every
    task description, so downstream agents cannot miss it.
    """
    required_dirs = extract_required_paths(requirement)
    if not required_dirs:
        return plan

    injected = apply_path_constraints(plan, required_dirs)
    if injected:
        print(f"[Planner] 已将缺失的路径约束注入任务描述: {injected}")
    else:
        print(
            f"[Planner] 路径约束已由模型逐任务落实，无需注入: {required_dirs}"
        )

    return plan


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

        plan = create_plan(task.description, llm=self.llm)

        return {
            "status": "planner_completed",
            "agent": self.role,
            "task_id": task.id,
            "plan": plan,
        }