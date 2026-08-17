import json

from config.model import client, AGNES_MODEL
from config.tools_schema import TOOLS_SCHEMA
from tools.registry import TOOLS


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

不要删除工作区之外的任何内容。

不要执行危险的系统级命令。

如果一个操作超出工作区权限，应停止并向用户说明。


====================
软件开发流程
====================

执行开发任务时：

1. 理解需求
2. 检查工作区
3. 找到相关项目
4. 阅读相关代码
5. 分析问题
6. 制定最小修改方案
7. 修改代码
8. 运行测试
9. 检查测试结果
10. 汇报最终结果

不要猜测文件内容。

修改代码之前先读取相关文件。

修改之后尽可能运行测试。

如果测试失败：

1. 分析错误
2. 修改代码
3. 再次测试

直到问题解决，或者明确告诉用户无法解决。


====================
最终回答
====================

汇报时使用逻辑上的工作区概念。

不要输出工作区的 Windows 物理路径。

例如：

正确：

"当前工作区为空。"

错误：

"当前工作区是 F:\\workspace\\..."
"""


class DeveloperAgent:

    def __init__(self):
        self.messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ]

    def run(self, task: str) -> str:

        self.messages.append(
            {
                "role": "user",
                "content": task,
            }
        )

        while True:

            response = client.chat.completions.create(
                model=AGNES_MODEL,
                messages=self.messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )

            message = response.choices[0].message

            if not message.tool_calls:

                return message.content or ""

            self.messages.append(message)

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
                        import inspect

                        tool_function = TOOLS[tool_name]

                        signature = inspect.signature(
                            tool_function
                        )

                        allowed_arguments = set(
                            signature.parameters.keys()
                        )

                        filtered_arguments = {
                            key: value
                            for key, value in arguments.items()
                            if key in allowed_arguments
                        }

                        ignored_arguments = {
                            key: value
                            for key, value in arguments.items()
                            if key not in allowed_arguments
                        }

                        if ignored_arguments:
                            print(
                                f"[Ignored Args] {ignored_arguments}"
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

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result),
                    }
                )