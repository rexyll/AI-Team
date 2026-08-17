from agents.developer import DeveloperAgent


agent = DeveloperAgent()


task = """
请在当前工作区创建一个新的 Python 项目：

项目名称：
calculator

需求：

1. 实现基本四则运算：
   - 加法
   - 减法
   - 乘法
   - 除法

2. 除法时需要正确处理除数为 0 的情况。

3. 编写 pytest 单元测试。

4. 测试应覆盖：
   - 正常计算
   - 负数
   - 小数
   - 除数为 0

5. 创建完成后运行所有测试。

6. 如果测试失败，请分析原因并修复。

7. 最终告诉我：
   - 创建了哪些文件
   - 实现了哪些功能
   - 测试结果
   - 是否全部通过

重要：

当前 "." 就是工作区根目录。

只能在当前工作区内创建和修改文件。

不要访问工作区之外的目录。

不要修改 ai-dev-team 本身。
"""


result = agent.run(task)


print("\n")
print("=" * 60)
print("FINAL RESULT")
print("=" * 60)
print(result)