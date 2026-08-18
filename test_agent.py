# from agents.developer import DeveloperAgent

# agent = DeveloperAgent()


# result = agent.run(
#     """
# 请检查当前工作区。

# 告诉我：

# 1. 当前工作区有哪些项目？
# 2. 每个项目有哪些文件？
# 3. 如果工作区为空，请明确告诉我。

# 重要：

# 当前 "." 就是工作区根目录。

# 不要使用 "projects" 作为路径。
# 不要访问 ".."。
# 不要访问工作区之外的目录。
# """
# )

# print("\n========== FINAL ANSWER ==========\n")
# print(result)


from agents.developer import DeveloperAgent
from runtime.task import Task


def test_developer_agent():

    task = Task(
        id="TEST-001",
        title="测试开发 Agent",
        description="测试 DeveloperAgent 是否能够正常运行",
        role="developer",
    )

    agent = DeveloperAgent()

    result = agent.run(task)

    assert result is not None
    assert result["status"] == "completed"
    assert result["agent"] == "developer"
    assert result["task_id"] == "TEST-001"