from agents.planner import create_plan


def test_planner_agent():

    requirement = """
    开发一个个人记账软件。

    要求：

    1. 支持收入和支出记录
    2. 支持分类
    3. 支持按月份统计
    4. 使用 SQLite 保存数据
    5. 提供 REST API
    6. 提供简单的 Web 页面
    7. 编写自动化测试
    """


    plan = create_plan(requirement)


    print()
    print("=" * 60)
    print("PROJECT PLAN")
    print("=" * 60)

    print()
    print(f"项目：{plan['project']}")
    print(f"摘要：{plan['summary']}")

    print()
    print("任务：")

    for task in plan["tasks"]:
        print()
        print(f"[{task['id']}]")
        print(f"标题：{task['title']}")
        print(f"角色：{task['role']}")
        print(f"描述：{task['description']}")
        print(f"依赖：{task['dependencies']}")