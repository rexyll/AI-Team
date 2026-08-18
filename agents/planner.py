import json

from config.model import ask_ai
from runtime.task_validator import validate_plan


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

必须严格输出 JSON。

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

规则：

1. task id 必须唯一。
2. dependencies 必须引用已经存在的 task id。
3. 每个任务必须足够具体，可以交给对应 Agent 执行。
4. 不要输出 Markdown。
5. 不要输出 ```json。
6. 不要输出 JSON 之外的任何内容。
"""


def create_plan(requirement: str) -> dict:
    prompt = f"""
请根据下面的软件需求制定开发计划：

{requirement}
"""

    response = ask_ai(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
    )

    response = response.strip()

    if response.startswith("```"):
        lines = response.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        response = "\n".join(lines).strip()

    try:
        plan = json.loads(response)

    except json.JSONDecodeError as exc:
        raise ValueError(
            "Planner 返回的内容不是合法 JSON。\n"
            f"原始响应：\n{response}"
        ) from exc

    validate_plan(plan)

    return plan