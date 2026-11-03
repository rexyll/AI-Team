"""UI/UX designer agent: interface design for projects with a visible UI.

Enabled by the project profile (web/desktop/mobile or explicit interface
signals) and injected into the plan as a design task before implementation.
Like the architect, this role works purely at the LLM level - it holds no
tool surface, writes no files and runs no commands - so design work cannot
touch product code. Its output feeds the Developer tasks that depend on it
and the delivery documentation set.
"""

from __future__ import annotations

from agents.base import BaseAgent
from runtime.agent_context import AgentContext
from runtime.agent_result import AgentResult
from runtime.context_view import context_view
from runtime.task import Task
from security.prompt_injection import untrusted_content

SYSTEM_PROMPT = """
你是一名资深 UI/UX 设计师（UI/UX Designer）。

职责：
1. 从用户任务出发设计信息架构与页面/视图结构
2. 定义布局、视觉层级与交互流程（含空态、加载态、错误态）
3. 给出可实施的设计规范：设计令牌（色彩/字体/间距）、组件边界、响应式断点
4. 明确可访问性要求（WCAG 2.1 AA：语义结构、键盘可达、对比度）
5. 给出可验证的可用性验收标准

工作原则：以用户任务为中心；设计必须能被工程师直接实现，避免不可落地的概念稿；
优先复用产品既有的视觉与技术约束。

你不编写业务代码、不修改文件、不执行命令、不调用任何工具。
"""


class UIDesignerAgent(BaseAgent):
    """Produce the UI/UX design specification for an interface-bearing product."""

    @property
    def role(self) -> str:
        return "ui_ux"

    def _build_messages(self, context: AgentContext, *, project_type: str) -> list[dict[str, str]]:
        view = context_view(context, self.role)
        prompt = f"""
请为下面的软件产品产出 UI/UX 设计规范。

====================
PROJECT
====================

项目类型：
{untrusted_content("profile.project_type", project_type)}

====================
TASK CONTEXT
====================

任务 ID：
{untrusted_content("task.id", view['task_id'])}

任务名称：
{untrusted_content("task.title", view['task_title'])}

任务描述：
{untrusted_content("task.description", view['task_description'])}

任务依赖：
{untrusted_content("task.dependencies", view['dependencies'])}

Dependency Context：
{untrusted_content("dependency.context", view['dependency_context'])}

Metadata：
{untrusted_content("task.metadata", view['metadata'])}

====================
DESIGN REQUIREMENTS
====================

请输出完整的设计规范，按以下顺序组织：

1. 用户与核心任务
2. 页面/视图清单与信息架构
3. 布局与视觉层级
4. 交互流程与状态设计（含空态、加载态、错误态）
5. 组件与设计令牌（色彩、字体、间距、圆角等）
6. 响应式断点与适配策略
7. 可访问性要求（WCAG 2.1 AA）
8. 可用性验收标准（可判成通过/不通过的表述）
9. 约束、风险与实现建议

不要编写业务代码，不要修改任何文件，不要输出工具调用语法。
"""
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

    def run(self, task: Task) -> AgentResult:
        if not isinstance(task, Task):
            raise TypeError(f"UIDesignerAgent.run() expects Task, got {type(task).__name__}")
        context = self.build_context(task)
        raw_project_type = task.context.get("project_type")
        project_type = raw_project_type if isinstance(raw_project_type, str) and raw_project_type.strip() else "general"
        messages = self._build_messages(context, project_type=project_type)
        specification = self._generate(
            messages[1]["content"],
            system_prompt=SYSTEM_PROMPT,
            max_tokens=4096,
        )
        return AgentResult(
            status="completed",
            agent=self.role,
            task_id=context.task_id,
            message=specification,
            data={"ui_ux": {"project_type": project_type, "spec": specification}},
        )
