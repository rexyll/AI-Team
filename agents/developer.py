import json
# import inspect

from config.model import client, AGNES_MODEL
from config.tools_schema import TOOLS_SCHEMA
from tools.registry import TOOLS
from agents.base import BaseAgent
from runtime.task import Task
from security.tool_guard import (
    validate_tool_arguments,
)

SYSTEM_PROMPT = """
你是一名专业的 AI 软件开发工程师。

你运行在 Windows 11 环境。

====================
工作区规则
====================

系统为你提供了一个受保护的项目工作区。

你只能操作这个工作区内部的文件。

你不需要知道工作区在 Windows 上的物理路径。

对你而言：

"." 表示工作区根目录。

例如：

"." 
表示工作区根目录。

"calculator"
表示工作区中的 calculator 项目目录。

"calculator/main.py"
表示 calculator 项目中的 main.py。

不要在路径前添加 "projects"。

错误示例：

"projects"
"../projects"
".."
"/"

正确示例：

"."
"calculator"
"calculator/main.py"


====================
文件操作规则
====================

查看目录：
优先使用 list_files。

读取文件：
使用 read_file。

修改文件：
使用 write_file。

不要使用 run_command 来代替文件工具。


====================
命令执行规则
====================

当前系统是 Windows 11。

run_command 使用 PowerShell。

只在以下情况下使用 run_command：

- 运行测试
- 运行构建
- 执行程序
- 执行专用开发工具
- 完成专用工具无法完成的操作

不要使用 Linux 命令，例如：

ls
cat
grep
rm
cp
mv

优先使用 Windows / PowerShell 命令。


====================
安全规则
====================

你只能操作授权工作区。

不要访问：

- 工作区之外的目录
- Windows 系统目录
- 用户目录
- Program Files
- 注册表
- 系统配置

不要执行危险的系统级命令。

如果一个操作超出工作区权限，应停止并向用户说明。


====================
软件开发流程
====================

执行开发任务时：

1. 理解任务
2. 阅读 Architect 提供的设计
3. 检查工作区
4. 找到相关项目
5. 阅读相关代码
6. 分析问题
7. 制定最小修改方案
8. 修改代码
9. 运行测试
10. 检查测试结果
11. 如果测试失败，分析并修复
12. 最后汇报完成情况

不要猜测文件内容。

修改代码之前必须先读取相关文件。

修改之后尽可能运行测试。

如果测试失败：

1. 分析错误
2. 修改代码
3. 再次测试

直到问题解决，或者明确告诉用户无法解决。


====================
Architect 协作规则
====================

Architect 的设计是重要的上游输入。

你必须认真阅读 Architect 提供的设计。

但是：

Architect 的设计不是绝对正确的。

如果发现：

- 明显的技术错误
- 设计矛盾
- 不合理的实现方式
- 与现有代码冲突

应该在最终结果中明确指出。

不要盲目照搬错误设计。


====================
代码修改原则
====================

遵循：

- 正确性优先
- 简单优先
- 最小修改
- 不进行无关重构
- 不修改无关文件
- 不引入不必要的依赖
- 保持现有代码风格


====================
最终回答
====================

最终回答应该说明：

1. 完成了什么
2. 修改了哪些文件
3. 运行了哪些测试
4. 测试结果
5. 是否存在遗留问题

不要输出工作区的 Windows 物理路径。
"""


class DeveloperAgent(BaseAgent):

    @property
    def role(self) -> str:
        return "developer"

    def _build_messages(self, task: Task):

        context_text = ""

        if task.context:

            context_text = """
            ====================
            UPSTREAM AGENT CONTEXT
            ====================

            以下内容来自上游 Agent。

            这些内容是当前任务的重要输入。

            如果上游 Agent 是 Architect：

            - 必须认真阅读架构设计
            - 优先按照架构设计实现
            - 不要无理由改变架构
            - 如果发现架构与现有代码冲突，应该分析后再决定
            - 如果必须偏离架构设计，应在最终报告中明确说明原因

            """

            for task_id, data in task.context.items():

                context_text += f"""
                --------------------
                Dependency: {task_id}
                Role: {data.get("role", "")}
                Title: {data.get("title", "")}
                --------------------

                """

                result = data.get("result", {})

                if isinstance(result, dict):

                    architecture = result.get(
                        "architecture"
                    )

                    if architecture:
                        context_text += (
                            "Architect Architecture Design:\n\n"
                        )
                        context_text += str(architecture)
                    else:
                        context_text += (
                            json.dumps(
                                result,
                                ensure_ascii=False,
                                indent=2,
                            )
                        )

                else:
                    context_text += str(result)

                context_text += "\n\n"

        if task.review:
            context_text += """
            ====================
            PREVIOUS REVIEW
            ====================

            上一次 Reviewer 的审核结果：

            """

            context_text += json.dumps(
                task.review,
                ensure_ascii=False,
                indent=2,
            )

            context_text += "\n\n"
        
        prompt = f"""
        ====================
        CURRENT TASK
        ====================

        Task ID:
        {task.id}

        Role:
        {task.role}

        Title:
        {task.title}

        Description:
        {task.description}

        Dependencies:
        {task.dependencies}

        {context_text}

        ====================
        EXECUTION REQUIREMENT
        ====================

        请完成当前开发任务。

        你拥有文件操作和命令执行工具。

        开始工作前先检查工作区并阅读相关代码。

        不要猜测文件内容。

        完成修改后运行相关测试。

        如果测试失败，请继续分析和修复。

        最终给出简洁的开发结果报告。
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

    def run(self, task: Task):

        if not isinstance(task, Task):
            raise TypeError(
                "DeveloperAgent.run() expects Task, "
                f"got {type(task).__name__}"
            )
        
        messages = self._build_messages(task)

        while True:

            response = client.chat.completions.create(
                model=AGNES_MODEL,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )

            message = response.choices[0].message

            if not message.tool_calls:

                result = message.content or ""

                return {
                    "status": "developer_completed",
                    "agent": self.role,
                    "task_id": task.id,
                    "message": result,
                }

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

                arguments = json.loads(
                    tool_call.function.arguments
                )

                print(
                    f"\n[Tool] {tool_name}"
                )

                print(
                    f"[Args] {arguments}"
                )

                if tool_name not in TOOLS:

                    result = (
                        f"Unknown tool: {tool_name}"
                    )

                else:

                    try:

                        tool_function = TOOLS[tool_name]

                        filtered_arguments, ignored_arguments = (
                            validate_tool_arguments(
                                tool_function,
                                arguments,
                            )
                        )

                        if ignored_arguments:

                            print(
                                f"[Ignored Args] "
                                f"{ignored_arguments}"
                            )

                        result = tool_function(
                            **filtered_arguments
                        )

                    except Exception as e:

                        result = (
                            f"Tool error: "
                            f"{type(e).__name__}: {e}"
                        )

                print(
                    f"[Result]\n{result}"
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result),
                    }
                )