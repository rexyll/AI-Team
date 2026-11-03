"""Deterministic project-type classification and specialist skill matching.

The team should not run a UI/UX designer for a command-line tool, nor a data
specialist for a browser page. This module maps the customer requirement
(plus the analyst draft and the plan text) to a stable project profile using
keyword rules only - no LLM call - so the same input always enables the same
specialists and the decision can be audited from the recorded signals.

The profile drives two things:

* a UI/UX design task injected into the plan when the deliverable has a
  visible interface (``apply_project_profile``);
* per-task developer skill matching: the matched specialist is recorded in
  ``task.context["developer_specialist"]`` and the Developer prompt receives
  the corresponding focus block (``classify_task_specialist`` /
  ``specialist_prompt``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PROJECT_TYPES: tuple[str, ...] = (
    "web",
    "desktop",
    "mobile",
    "api",
    "data",
    "cli",
    "library",
    "general",
)

UI_PROJECT_TYPES = frozenset({"web", "desktop", "mobile"})

_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "web": (
        "网站",
        "网页",
        "web应用",
        "web 应用",
        "浏览器",
        "前端",
        "frontend",
        "html",
        "css",
        "javascript",
        "typescript",
        "react",
        "vue",
        "angular",
        "后台管理",
        "管理后台",
        "仪表盘",
        "dashboard",
        "spa",
        "响应式网页",
    ),
    "desktop": (
        "桌面应用",
        "桌面端",
        "桌面程序",
        "desktop",
        "windows应用",
        "windows 应用",
        "gui",
        "tkinter",
        "pyqt",
        "pyside",
        "wpf",
        "winforms",
        "electron",
    ),
    "mobile": (
        "移动应用",
        "移动端",
        "手机应用",
        "安卓",
        "android",
        "ios",
        "小程序",
        "flutter",
        "react native",
        "鸿蒙",
        "harmonyos",
    ),
    "api": (
        "api",
        "rest",
        "restful",
        "微服务",
        "服务端",
        "后端",
        "backend",
        "接口服务",
        "http服务",
        "http 服务",
        "fastapi",
        "flask",
        "django",
        "grpc",
    ),
    "data": (
        "数据管道",
        "数据清洗",
        "etl",
        "报表",
        "数据分析",
        "数据仓库",
        "数据平台",
        "pipeline",
        "pandas",
        "spark",
        "指标计算",
    ),
    "cli": (
        "cli",
        "命令行",
        "终端工具",
        "shell工具",
        "shell 工具",
        "command line",
        "命令行工具",
        "脚本工具",
    ),
    "library": (
        "开发库",
        "类库",
        "library",
        "sdk",
        "python包",
        "python 包",
        "npm包",
        "npm 包",
        "组件库",
    ),
}

# Strong interface signals: they make the UI/UX role relevant even when the
# project type is not explicitly a GUI platform (e.g. "学生管理系统的界面").
_UI_KEYWORDS: tuple[str, ...] = (
    "界面",
    "页面",
    "前端",
    "ui/ux",
    "ui",
    "ux",
    "交互",
    "布局",
    "视觉",
    "样式",
    "主题",
    "表单",
    "弹窗",
    "导航",
    "响应式",
    "可访问性",
    "无障碍",
    "用户体验",
    "原型",
    "仪表盘",
    "dashboard",
    "gui",
    "窗口",
)

_SPECIALIST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "frontend": (
        "前端",
        "页面",
        "界面",
        "组件",
        "样式",
        "交互",
        "布局",
        "css",
        "html",
        "javascript",
        "typescript",
        "react",
        "vue",
        "ui/ux",
        "ui",
        "ux",
    ),
    "backend": (
        "后端",
        "服务端",
        "接口",
        "api",
        "数据库",
        "持久化",
        "认证",
        "鉴权",
        "并发",
        "队列",
        "backend",
        "sql",
        "缓存",
    ),
    "data": (
        "数据",
        "etl",
        "报表",
        "分析",
        "指标",
        "管道",
        "清洗",
        "pipeline",
        "pandas",
        "spark",
        "统计",
    ),
    "desktop": (
        "桌面",
        "gui",
        "窗口",
        "tkinter",
        "pyqt",
        "wpf",
        "electron",
        "打包",
    ),
    "mobile": (
        "移动",
        "安卓",
        "android",
        "ios",
        "小程序",
        "flutter",
        "app",
        "鸿蒙",
        "harmonyos",
    ),
    "cli": (
        "cli",
        "命令行",
        "终端",
        "参数",
        "退出码",
        "管道",
        "argparse",
        "子命令",
    ),
}

DEVELOPER_SPECIALISTS: dict[str, tuple[str, ...]] = {
    "web": ("frontend", "backend"),
    "desktop": ("desktop",),
    "mobile": ("mobile",),
    "api": ("backend",),
    "data": ("data",),
    "cli": ("cli",),
    "library": (),
    "general": (),
}

SPECIALIST_LABELS: dict[str, str] = {
    "frontend": "前端工程师",
    "backend": "后端工程师",
    "data": "数据工程师",
    "desktop": "桌面工程师",
    "mobile": "移动端工程师",
    "cli": "命令行工具工程师",
}

SPECIALIST_PROMPTS: dict[str, str] = {
    "frontend": (
        "本轮你承担【前端工程师】专项职责：优先保证页面结构与交互可用性，"
        "实现遵循 UI/UX 设计规范（布局、组件边界、设计令牌、状态与空态）；"
        "注意响应式断点、可访问性（语义结构、键盘可达、对比度）与浏览器兼容性；"
        "样式与逻辑分离，避免把业务规则硬编码进视图层。"
    ),
    "backend": (
        "本轮你承担【后端工程师】专项职责：先明确接口契约（输入、输出、错误码），"
        "再实现处理逻辑；所有外部输入必须校验，异常路径必须显式处理；"
        "数据持久化保持事务性与幂等性，敏感信息不落日志；为接口编写可复现的自动化测试。"
    ),
    "data": (
        "本轮你承担【数据工程师】专项职责：保证数据管道可重跑且幂等，"
        "显式处理空值、重复记录与异常行；统计口径与指标定义写入代码注释或文档；"
        "大输入分块处理，避免一次性载入内存；用样例数据验证结果可复现。"
    ),
    "desktop": (
        "本轮你承担【桌面工程师】专项职责：注意窗口生命周期、主线程与后台任务边界、"
        "跨平台路径与文件系统差异；交互阻塞不得卡死界面；打包入口与运行命令必须实测可用。"
    ),
    "mobile": (
        "本轮你承担【移动端工程师】专项职责：遵循目标平台交互规范，"
        "处理权限、离线与弱网状态、生命周期与后台切换；控制资源占用，保证安装包可构建。"
    ),
    "cli": (
        "本轮你承担【命令行工具工程师】专项职责：保证命令帮助文本准确、参数校验清晰、"
        "退出码语义正确（成功 0 / 失败非 0）、输出对管道友好；错误信息可直接指导用户修复。"
    ),
}

_ASCII_WORD = re.compile(r"[a-z0-9]")
_MAX_SIGNALS = 12


def _count_keyword(text: str, keyword: str) -> int:
    """Count whole-word ASCII keywords, substring CJK keywords."""
    if keyword.isascii() and keyword.replace(" ", "").isalnum():
        pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
        return len(re.findall(pattern, text))
    return text.count(keyword)


def _plan_text(plan: dict[str, Any] | None) -> str:
    if not isinstance(plan, dict):
        return ""
    parts: list[str] = []
    for key in ("project", "summary"):
        value = plan.get(key)
        if isinstance(value, str):
            parts.append(value)
    tasks = plan.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            for key in ("title", "description"):
                value = task.get(key)
                if isinstance(value, str):
                    parts.append(value)
    return "\n".join(parts)


def _weighted_texts(
    requirement: str,
    analysis: str,
    plan: dict[str, Any] | None,
) -> list[tuple[str, int]]:
    """Requirement text dominates; analyst/plan text only reinforces it."""
    texts: list[tuple[str, int]] = [(requirement.lower(), 2)]
    if analysis.strip():
        texts.append((analysis.lower(), 1))
    plan_text = _plan_text(plan).lower()
    if plan_text.strip():
        texts.append((plan_text, 1))
    return texts


def _type_scores(texts: list[tuple[str, int]]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for project_type in PROJECT_TYPES:
        keywords = _TYPE_KEYWORDS.get(project_type, ())
        scores[project_type] = sum(
            weight * sum(_count_keyword(text, keyword) for keyword in keywords)
            for text, weight in texts
        )
    return scores


@dataclass(frozen=True)
class ProjectProfile:
    """Deterministic project classification used to enable specialists."""

    project_type: str
    signals: tuple[str, ...] = ()
    ui_required: bool = False
    specialists: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.project_type not in PROJECT_TYPES:
            raise ValueError(f"unsupported project_type: {self.project_type!r}")
        if not isinstance(self.signals, tuple):
            raise TypeError("signals must be a tuple")
        if not isinstance(self.ui_required, bool):
            raise TypeError("ui_required must be a bool")
        if not isinstance(self.specialists, tuple):
            raise TypeError("specialists must be a tuple")

    def specialist_for(self, *, title: str, description: str) -> str | None:
        return classify_task_specialist(title=title, description=description, profile=self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_type": self.project_type,
            "ui_required": self.ui_required,
            "specialists": list(self.specialists),
            "signals": list(self.signals),
        }


def detect_project_profile(
    requirement: str,
    analysis: str = "",
    plan: dict[str, Any] | None = None,
) -> ProjectProfile:
    """Classify the project from requirement/analysis/plan text.

    Highest weighted keyword score wins; ties keep the fixed ``PROJECT_TYPES``
    priority (web before desktop before mobile ...). Without any signal the
    profile is ``general`` and no specialist is enabled.
    """
    if not isinstance(requirement, str):
        raise TypeError("requirement must be a string")
    if not isinstance(analysis, str):
        raise TypeError("analysis must be a string")
    texts = _weighted_texts(requirement, analysis, plan)
    scores = _type_scores(texts)
    best_type = max(PROJECT_TYPES, key=lambda item: scores[item])
    if scores[best_type] <= 0:
        best_type = "general"

    requirement_text = texts[0][0]
    ui_signals = tuple(
        keyword
        for keyword in _UI_KEYWORDS
        if _count_keyword(requirement_text, keyword) > 0
    )
    ui_required = best_type in UI_PROJECT_TYPES or bool(ui_signals)

    signals: list[str] = []
    for project_type in PROJECT_TYPES:
        for keyword in _TYPE_KEYWORDS.get(project_type, ()):
            if any(_count_keyword(text, keyword) > 0 for text, _weight in texts):
                signals.append(f"{project_type}:{keyword}")
    for keyword in ui_signals:
        signals.append(f"ui:{keyword}")
    specialists = ((("ui_ux",) if ui_required else ()) + DEVELOPER_SPECIALISTS[best_type])
    return ProjectProfile(
        project_type=best_type,
        signals=tuple(signals[:_MAX_SIGNALS]),
        ui_required=ui_required,
        specialists=specialists,
    )


def _task_text(title: str, description: str) -> str:
    return f"{title}\n{description}".lower()


def classify_task_specialist(
    *,
    title: str,
    description: str,
    profile: ProjectProfile | None,
) -> str | None:
    """Match one developer task to an enabled specialist.

    Only specialists enabled by the project profile can be assigned. A task
    without matching keywords keeps the generic Developer (no overclaiming).
    """
    if not isinstance(title, str) or not isinstance(description, str):
        raise TypeError("title and description must be strings")
    if not isinstance(profile, ProjectProfile) and profile is not None:
        raise TypeError("profile must be a ProjectProfile or None")
    if profile is None:
        return None
    enabled = tuple(item for item in profile.specialists if item != "ui_ux")
    if not enabled:
        return None
    text = _task_text(title, description)
    scores = {
        specialist: sum(
            _count_keyword(text, keyword)
            for keyword in _SPECIALIST_KEYWORDS.get(specialist, ())
        )
        for specialist in enabled
    }
    best = max(enabled, key=lambda item: scores[item])
    if scores[best] <= 0:
        return None
    return best


def specialist_prompt(specialist: str | None) -> str:
    """Return the focus block for an enabled specialist ('' when none)."""
    if specialist is None:
        return ""
    if not isinstance(specialist, str):
        raise TypeError("specialist must be a string or None")
    return SPECIALIST_PROMPTS.get(specialist, "")


_UI_TASK_KEYWORDS: tuple[str, ...] = (
    "界面",
    "页面",
    "前端",
    "ui",
    "ux",
    "交互",
    "布局",
    "样式",
    "组件",
    "导航",
    "表单",
    "仪表盘",
    "dashboard",
    "gui",
)


def _next_task_id(existing_ids: set[str], base: str = "UX-001") -> str:
    prefix, _, number = base.rpartition("-")
    index = int(number)
    candidate = f"{prefix}-{index:03d}"
    while candidate in existing_ids:
        index += 1
        candidate = f"{prefix}-{index:03d}"
    return candidate


def apply_project_profile(
    plan: dict[str, Any],
    profile: ProjectProfile,
    *,
    ui_ux_enabled: bool,
) -> dict[str, Any]:
    """Enable (or downgrade) the UI/UX role in a validated plan.

    ``ui_ux_enabled`` reflects whether the runtime has a registered ui_ux
    agent. Plans produced before the role existed (or by a model ignoring the
    role restriction) are handled deterministically: ui_ux is only kept when
    both the profile requires an interface and the agent is available;
    otherwise such tasks become regular architecture tasks so the graph stays
    executable.
    """
    if not isinstance(plan, dict):
        raise TypeError("plan must be a dictionary")
    if not isinstance(profile, ProjectProfile):
        raise TypeError("profile must be a ProjectProfile")
    if not isinstance(ui_ux_enabled, bool):
        raise TypeError("ui_ux_enabled must be a bool")

    tasks = [dict(task) for task in plan["tasks"]]
    enabled = ui_ux_enabled and profile.ui_required
    existing_ux = [task for task in tasks if task.get("role") == "ui_ux"]

    if not enabled:
        if not existing_ux:
            return plan
        for task in tasks:
            if task.get("role") == "ui_ux":
                task["role"] = "architect"
        return {**plan, "tasks": tasks}

    ui_targets = [
        task
        for task in tasks
        if task.get("role") == "developer"
        and any(keyword in _task_text(task.get("title", ""), task.get("description", "")) for keyword in _UI_TASK_KEYWORDS)
    ]
    if not ui_targets:
        ui_targets = [task for task in tasks if task.get("role") == "developer"][:1]

    if existing_ux:
        ux_id = str(existing_ux[0]["id"])
        for task in ui_targets:
            dependencies = list(task.get("dependencies") or [])
            if ux_id not in dependencies:
                task["dependencies"] = [*dependencies, ux_id]
        return {**plan, "tasks": tasks}

    existing_ids = {str(task.get("id")) for task in tasks}
    ux_id = _next_task_id(existing_ids)
    architect_ids = [
        str(task["id"]) for task in tasks if task.get("role") == "architect"
    ]
    ux_task = {
        "id": ux_id,
        "title": "UI/UX 设计规范",
        "description": (
            f"基于需求规格与架构设计，产出可直接落地的 UI/UX 设计规范（项目类型：{profile.project_type}）："
            "页面/视图清单与信息架构、布局与视觉层级、交互流程与状态（含空态/加载态/错误态）、"
            "组件与设计令牌（色彩/字体/间距）、响应式断点、可访问性（WCAG）要求与可用性验收标准。"
            "不编写业务代码、不修改文件、不执行命令。"
        ),
        "role": "ui_ux",
        "dependencies": architect_ids,
    }
    for task in ui_targets:
        dependencies = list(task.get("dependencies") or [])
        if ux_id not in dependencies:
            task["dependencies"] = [*dependencies, ux_id]
    return {**plan, "tasks": [*tasks, ux_task]}
