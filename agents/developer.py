import json
from datetime import datetime, timezone
from typing import Any

from config.model import client, AGNES_MODEL
from tools.registry import TOOL_REGISTRY, TOOLS
from agents.base import BaseAgent
from runtime.task import Task
from runtime.agent_context import AgentContext
from runtime.context_view import context_view
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord
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

最终汇报时必须说明：

- 完成了什么
- 修改了哪些文件
- 执行了哪些测试
- 测试结果
- 是否存在遗留问题
"""


class DeveloperAgent(BaseAgent):

    @property
    def role(self) -> str:
        return "developer"

    def _build_messages(self, context: AgentContext):
        view = context_view(context, self.role)
        context_text = ""

        if view["dependency_context"]:
            context_text += (
                "\n====================\n"
                "UPSTREAM AGENT CONTEXT\n"
                "====================\n"
            )

            for context_key, data in view["dependency_context"].items():
                if not isinstance(data, dict):
                    continue

                context_text += (
                    f"\nDependency: {context_key}\n"
                    f"Role: {data.get('role', '')}\n"
                    f"Title: {data.get('title', '')}\n"
                )

                result = data.get("result", {})

                if isinstance(result, dict):
                    architecture = result.get("architecture")

                    if architecture:
                        context_text += (
                            "\nArchitect Architecture Design:\n"
                            + str(architecture)
                        )
                    else:
                        context_text += json.dumps(
                            result,
                            ensure_ascii=False,
                            indent=2,
                        )
                else:
                    context_text += str(result)

                context_text += "\n"

        if view["reviewer_feedback"]:
            context_text += """
            ====================
            PREVIOUS REVIEW FEEDBACK
            ====================

            以下是上一轮 Reviewer 给出的修改意见。
            本轮必须认真处理这些意见，并在最终结果中说明如何解决。

            """

            context_text += json.dumps(
                view["reviewer_feedback"],
                ensure_ascii=False,
                indent=2,
            )

        prompt = f"""
        ====================
        CURRENT TASK
        ====================

        Task ID: {view['task_id']}
        Role: {view['role']}
        Title: {view['task_title']}
        Description: {view['task_description']}
        Status: {view['status']}
        Dependencies: {view['dependencies']}

        Current Task Result:
        {view['task_result']}

        Tester Feedback:
        {view['tester_feedback']}

        Review Round:
        {view['review_round']}

        Execution History:
        {view['history']}

        Metadata:
        {view['metadata']}

        {context_text}

        ====================
        EXECUTION REQUIREMENT
        ====================

        请完成当前开发任务。

        开始工作前先检查工作区并阅读相关代码。

        完成修改后运行相关测试。
        如果测试失败，请继续分析和修复。

        最终给出简洁的开发结果报告。

        报告必须包含：

        1. 完成内容
        2. 修改文件
        3. 测试命令
        4. 测试结果
        5. 遗留问题
        """

        return [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

    def run(self, task: Task) -> AgentResult:
        if not isinstance(task, Task):
            raise TypeError(
                "DeveloperAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )

        context = self.build_context(task)
        messages = self._build_messages(context)
        persisted_history = task.context.get("tool_execution_history")
        if persisted_history is None:
            self.tool_execution_history = ToolExecutionHistory()
        else:
            try:
                self.tool_execution_history = ToolExecutionHistory.from_dict(persisted_history)
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(
                    f"task {task.id} contains invalid persisted tool execution history"
                ) from exc

        changed_files: list[str] = []
        command_results: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.chat.completions.create(
                model=AGNES_MODEL,
                messages=messages,
                tools=TOOL_REGISTRY.schemas(),
                tool_choice="auto",
            )

            message = response.choices[0].message

            if not message.tool_calls:
                content = message.content or ""

                data = self._build_result_data(
                    content=content,
                    changed_files=changed_files,
                    command_results=command_results,
                    tool_calls=tool_calls,
                )

                return AgentResult(
                    status="completed",
                    agent=self.role,
                    task_id=context.task_id,
                    message=content,
                    data=data,
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
                started_at = datetime.now(timezone.utc).isoformat()
                status = "completed"
                result: Any = None
                error: Any = None
                record_arguments: dict[str, Any] = {}

                print(f"\n[Tool] {tool_name}")

                try:
                    arguments = json.loads(tool_call.function.arguments)
                except (TypeError, json.JSONDecodeError) as exc:
                    status = "invalid_arguments"
                    error = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    result = (
                        "Tool error: invalid JSON arguments: "
                        f"{type(exc).__name__}: {exc}"
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result,
                        }
                    )
                    self._record_tool_execution(
                        execution_id=tool_call.id,
                        task_id=context.task_id,
                        tool_name=tool_name,
                        started_at=started_at,
                        status=status,
                        arguments=record_arguments,
                        output=None,
                        error=error,
                    )
                    continue

                if not isinstance(arguments, dict):
                    status = "invalid_arguments"
                    error = {
                        "type": "TypeError",
                        "message": "tool arguments must be a JSON object",
                    }
                    result = "Tool error: arguments must be a JSON object"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result,
                        }
                    )
                    self._record_tool_execution(
                        execution_id=tool_call.id,
                        task_id=context.task_id,
                        tool_name=tool_name,
                        started_at=started_at,
                        status=status,
                        arguments=record_arguments,
                        output=None,
                        error=error,
                    )
                    continue

                print(f"[Args] {arguments}")

                try:
                    tool_function = TOOL_REGISTRY.get(tool_name)
                    tool_schema = TOOL_REGISTRY.schema(tool_name)

                    (
                        validated_arguments,
                        ignored_arguments,
                    ) = validate_tool_arguments(
                        tool_function,
                        arguments,
                        schema=tool_schema,
                    )
                    record_arguments = dict(validated_arguments)

                    if ignored_arguments:
                        print(
                            "[Ignored Args] "
                            f"{ignored_arguments}"
                        )

                    tool_calls.append(
                        {
                            "name": tool_name,
                            "arguments": dict(validated_arguments),
                        }
                    )

                    result = tool_function(**validated_arguments)

                    self._record_tool_evidence(
                        tool_name=tool_name,
                        arguments=validated_arguments,
                        result=result,
                        changed_files=changed_files,
                        command_results=command_results,
                    )
                except KeyError:
                    status = "unknown_tool"
                    error = {
                        "type": "KeyError",
                        "message": f"Unknown tool: {tool_name}",
                    }
                    result = f"Unknown tool: {tool_name}"
                except Exception as exc:
                    status = "failed"
                    error = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    result = (
                        "Tool error: "
                        f"{type(exc).__name__}: {exc}"
                    )

                print(f"[Result]\n{result}")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result),
                    }
                )

                self._record_tool_execution(
                    execution_id=tool_call.id,
                    task_id=context.task_id,
                    tool_name=tool_name,
                    started_at=started_at,
                    status=status,
                    arguments=record_arguments,
                    output=result if status == "completed" else None,
                    error=error,
                )

        raise RuntimeError(
            "Developer tool loop exceeded maximum iterations: "
            f"{MAX_TOOL_ITERATIONS}"
        )

    def _record_tool_execution(
        self,
        *,
        execution_id: str,
        task_id: str,
        tool_name: str,
        started_at: str,
        status: str,
        arguments: dict[str, Any],
        output: Any,
        error: Any,
    ) -> None:
        self.tool_execution_history.append(
            ToolExecutionRecord(
                execution_id=execution_id,
                task_id=task_id,
                agent_role=self.role,
                tool_name=tool_name,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                status=status,
                arguments=arguments,
                output=output,
                error=error,
            )
        )

    @staticmethod
    def _record_tool_evidence(
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        changed_files: list[str],
        command_results: list[dict[str, Any]],
    ) -> None:
        """Record factual execution evidence from Developer tool calls."""
        if tool_name == "write_file":
            path = arguments.get("path")
            if isinstance(path, str) and path and path not in changed_files:
                changed_files.append(path)

        if tool_name == "run_command":
            command = arguments.get("command")
            if isinstance(command, str) and command:
                command_results.append(
                    {
                        "command": command,
                        "result": str(result),
                    }
                )

    @staticmethod
    def _build_result_data(
        *,
        content: str,
        changed_files: list[str],
        command_results: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build the structured Developer Result payload."""
        return {
            "summary": content.strip(),
            "files_changed": list(changed_files),
            "tests": list(command_results),
            "validation": {
                "tool_call_count": len(tool_calls),
                "test_command_count": len(command_results),
                "files_changed_count": len(changed_files),
            },
            "report": content,
        }
