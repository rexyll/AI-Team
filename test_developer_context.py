from agents.developer import DeveloperAgent
from runtime.task import Task

def test_developer_context():
    
    task = Task(
        id="TASK-003",
        title="检查计算器项目",
        description="""
    检查当前 calculator 项目。

    要求：

    1. 查看项目结构
    2. 阅读 calculator.py
    3. 阅读测试文件
    4. 判断当前实现是否存在明显问题

    本次任务只进行代码检查。

    不要修改任何文件。
    不要创建任何文件。
    """,
        role="developer",
        dependencies=["TASK-001"],
    )


    task.context = {
        "TASK-001": {
            "role": "architect",
            "title": "数据库 Schema 设计",
            "result": {
                "architecture": """
    这是来自 Architect 的测试设计。

    当前测试任务与该设计没有直接关系。
    Developer 应该识别这一点，不应该修改 calculator 项目。
    """
            },
        }
    }


    agent = DeveloperAgent()


    print()
    print("=" * 60)
    print("DEVELOPER CONTEXT TEST")
    print("=" * 60)

    result = agent.run(task)


    print()
    print("=" * 60)
    print("DEVELOPER RESULT")
    print("=" * 60)

    print(result["message"])