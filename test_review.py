from agents.developer import DeveloperAgent
from runtime.task import Task


# agent = DeveloperAgent()


# task = """
# 请对刚才创建的 calculator 项目进行一次结构审查。

# 项目要求：

# calculator 项目必须采用以下结构：

# calculator/
# ├── calculator.py
# ├── __init__.py
# └── test_calculator.py

# 要求：

# 1. test_calculator.py 必须位于 calculator 目录内部。
# 2. 不允许在项目根目录创建 tests 目录来存放这个项目的测试。
# 3. 检查当前项目实际结构。
# 4. 如果发现结构不符合要求，请自行修复。
# 5. 修复后重新运行 pytest。
# 6. 确认所有测试仍然通过。
# 7. 不要修改与 calculator 项目无关的文件。

# 最终报告：

# - 修改了哪些文件
# - 删除了哪些不需要的文件
# - 当前项目结构
# - pytest 测试结果
# """


# result = agent.run(task)


# print("\n")
# print("=" * 60)
# print("REVIEW RESULT")
# print("=" * 60)
# print(result)

# def test_review_agent():

#     task = Task(
#         id="TEST-003",
#         title="代码审查",
#         description="审查当前代码",
#         role="reviewer",
#     )

#     agent = ReviewerAgent()

#     result = agent.run(task)

#     assert result is not None
#     assert result["status"] == "completed"