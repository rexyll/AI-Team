import json

from config.model import client, AGNES_MODEL
from config.tools_schema import TOOLS_SCHEMA
from tools.registry import TOOLS
from agents.base import BaseAgent
from runtime.task import Task
from security.tool_guard import validate_tool_arguments
from runtime.agent_result import AgentResult

MAX_TOOL_ITERATIONS = 50


SYSTEM_PROMPT = """
你是一名专业的 AI 软件开发工程师。
你运行在 Windows 11 环境。

你只能操作受保护的项目工作区。
对你而言，"." 表示工作区根目录。
不要访问工作区之外的目录、系统目录、用户目录、Program Files、注册表或系统配置。

查看目录优先使用 list_files，读取文件使用 read_file，修改文件使用 write_file。
不要使用 run_command 代替文件工具。
run_command 只用于测试、构建、执行程序或专用开发工具。

执行开发任务时：
1. 理解任务
2. 阅读 Architect 提供的设计
3. 检查工作区
4. 阅读相关代码
5. 分析问题
6. 制定最小修改方案
7. 修改代码
8. 运行测试
9. 检查测试结果
10. 必要时继续修复
11. 汇报完成情况

修改代码之前必须先读取相关文件。
遵循正确性优先、简单优先、最小修改、不进行无关重构的原则。
"""


class DeveloperAgent(BaseAgent):
    @property
    def role(self) -> str:
        return "developer"

    def _build_messages(self, task: Task):
        context_text = ""

        if task.context:
            context_text += "\n====================\nUPSTREAM AGENT CONTEXT\n====================\n"
            for context_key, data in task.context.items():
                if context_key == "reviewer_feedback":
                    continue

                context_text += f"\nDependency: {context_key}\nRole: {data.get('role', '')}\nTitle: {data.get('title', '')}\n"
                result = data.get("result", {})
                if isinstance(result, dict):
                    architecture = result.get("architecture")
                    if architecture:
                        context_text += "\nArchitect Architecture Design:\n" + str(architecture)
                    else:
                        context_text += json.dumps(result, ensure_ascii=False, indent=2)
                else:
                    context_text += str(result)
                context_text += "\n"

        reviewer_feedback = task.context.get("reviewer_feedback")
        if reviewer_feedback:
            context_text += """
            ====================
            PREVIOUS REVIEW FEEDBACK
            ====================

            以下是上一轮 Reviewer 给出的修改意见。
            本轮必须认真处理这些意见，并在最终结果中说明如何解决。

            """
            context_text += json.dumps(
                reviewer_feedback,
                ensure_ascii=False,
                indent=2,
            )

        prompt = f"""
        ====================
        CURRENT TASK
        ====================
        Task ID: {task.id}
        Role: {task.role}
        Title: {task.title}
        Description: {task.description}
        Dependencies: {task.dependencies}
        {context_text}

        ====================
        EXECUTION REQUIREMENT
        ====================
        请完成当前开发任务。
        开始工作前先检查工作区并阅读相关代码。
        完成修改后运行相关测试。如果测试失败，请继续分析和修复。
        最终给出简洁的开发结果报告。
        """

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    def run(self, task: Task):
        if not isinstance(task, Task):
            raise TypeError(
                "DeveloperAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )

        messages = self._build_messages(task)

        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.chat.completions.create(
                model=AGNES_MODEL,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )

            message = response.choices[0].message

            if not message.tool_calls:
                return AgentResult(
                    status="completed",
                    agent="developer",
                    task_id=task.id,
                    message=message,
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                        for tool_call in message.tool_calls
                    ],
                }
            )

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                print(f"\n[Tool] {tool_name}")

                try:
                    arguments = json.loads(tool_call.function.arguments)
                except (TypeError, json.JSONDecodeError) as exc:
                    result = f"Tool error: invalid JSON arguments: {type(exc).__name__}: {exc}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                    continue

                print(f"[Args] {arguments}")

                if tool_name not in TOOLS:
                    result = f"Unknown tool: {tool_name}"
                else:
                    try:
                        tool_function = TOOLS[tool_name]
                        filtered_arguments, ignored_arguments = validate_tool_arguments(
                            tool_function,
                            arguments,
                        )
                        if ignored_arguments:
                            print(f"[Ignored Args] {ignored_arguments}")
                        result = tool_function(**filtered_arguments)
                    except Exception as exc:
                        result = f"Tool error: {type(exc).__name__}: {exc}"

                print(f"[Result]\n{result}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

        raise RuntimeError(
            f"Developer tool loop exceeded maximum iterations: {MAX_TOOL_ITERATIONS}"
        )
