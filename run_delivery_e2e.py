"""Launcher for the live delivery E2E (avoids shell quoting issues)."""
import json
import sys

from main import run_project

REQUIREMENT = (
    "开发一个Python命令行待办事项管理工具,所有文件放在 workspace/e2e_delivery/ 目录下:"
    "提供 todo.py,支持添加任务(python todo.py add \"买牛奶\")、列出全部任务(python todo.py list)、"
    "完成任务(python todo.py done 1),数据保存在 JSON 文件中;必须包含单元测试且实际运行通过;提供 README.md。"
)

task_manager, result = run_project(REQUIREMENT)
print("===E2E-RESULT===")
print(json.dumps({
    "success": result.success,
    "status": result.status,
    "completed_task_ids": list(result.completed_task_ids),
    "failed_tasks": list(result.failed_tasks),
}, ensure_ascii=False))
