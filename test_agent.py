from agents.developer import DeveloperAgent


agent = DeveloperAgent()


result = agent.run(
    """
请检查当前工作区。

告诉我：

1. 当前工作区有哪些项目？
2. 每个项目有哪些文件？
3. 如果工作区为空，请明确告诉我。

重要：

当前 "." 就是工作区根目录。

不要使用 "projects" 作为路径。
不要访问 ".."。
不要访问工作区之外的目录。
"""
)

print("\n========== FINAL ANSWER ==========\n")
print(result)