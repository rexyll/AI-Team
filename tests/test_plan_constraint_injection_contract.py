"""Path-constraint enforcement contracts for planner output.

Three consecutive real-provider runs dropped the requirement's mandated
output directory ("workspace/stringkit/") from generated plans. Prompt
guidance alone did not close the gap, so plan post-processing now
mechanically injects missing directory constraints. These contracts pin
the extraction and injection semantics.
"""

from __future__ import annotations

import pytest

from runtime.plan_constraints import (
    apply_path_constraints,
    extract_required_paths,
)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extracts_directory_constraint_from_requirement() -> None:
    requirement = "开发一个工具包。所有文件放在 workspace/stringkit/ 目录下。"
    assert extract_required_paths(requirement) == ["workspace/stringkit"]


def test_extraction_requires_at_least_two_segments() -> None:
    assert extract_required_paths("把文件放在 workspace 目录下") == []
    assert extract_required_paths("没有任何路径信息的需求") == []


def test_extraction_skips_file_specifications() -> None:
    # File specs carry an extension in the last segment; they are concrete
    # enough to reach descriptions verbatim and must not become dir mandates.
    requirement = "实现 stringkit/utils.py 和 docs/readme.md，放在 src/ 下"
    assert extract_required_paths(requirement) == ["src"]


def test_extraction_ignores_urls_and_dedupes() -> None:
    requirement = (
        "参考 https://example.com/a/b 文档。"
        "产物放在 output/pkg/ 与 OUTPUT/PKG/ 目录下。"
    )
    assert extract_required_paths(requirement) == ["output/pkg"]


def test_extraction_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        extract_required_paths(None)


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


def _plan(*descriptions: str) -> dict:
    return {
        "project": "demo",
        "summary": "demo",
        "tasks": [
            {"id": f"TASK-{index:03d}", "description": description}
            for index, description in enumerate(descriptions, start=1)
        ],
    }


def test_injects_missing_constraint_into_every_task() -> None:
    plan = _plan("架构设计", "实现 utils 模块", "编写测试")

    injected = apply_path_constraints(plan, ["workspace/stringkit"])

    assert injected == ["workspace/stringkit"]
    marker = "【用户约束】所有文件必须放在 workspace/stringkit/ 目录下。"
    for task in plan["tasks"]:
        assert task["description"].endswith(marker)


def test_injection_is_idempotent() -> None:
    plan = _plan("实现 utils 模块")

    first = apply_path_constraints(plan, ["workspace/stringkit"])
    second = apply_path_constraints(plan, ["workspace/stringkit"])

    assert first == ["workspace/stringkit"]
    assert second == []
    assert plan["tasks"][0]["description"].count("【用户约束】") == 1


def test_noop_when_constraint_already_present() -> None:
    plan = _plan("在 workspace/stringkit/ 下实现全部模块")

    injected = apply_path_constraints(plan, ["workspace/stringkit"])

    assert injected == []
    assert "【用户约束】" not in plan["tasks"][0]["description"]


def test_plan_wide_mention_does_not_cover_other_tasks() -> None:
    """run5 regression: one architect task echoing the requirement sentence
    must NOT count as coverage for developer tasks that lack the path."""
    plan = _plan(
        "架构设计：需求原文要求所有文件放在 workspace/stringkit/ 目录下",
        "实现 stringkit/utils.py 核心函数",   # 无路径 → 必须注入
        "编写单元测试",                        # 无路径 → 必须注入
    )

    injected = apply_path_constraints(plan, ["workspace/stringkit"])

    assert injected == ["workspace/stringkit"]
    # 提及过的任务不重复注入；未提及的两个任务各获得一行约束。
    assert "【用户约束】" not in plan["tasks"][0]["description"]
    for task in plan["tasks"][1:]:
        assert (
            "【用户约束】所有文件必须放在 workspace/stringkit/ 目录下。"
            in task["description"]
        )


def test_noop_for_plan_without_tasks() -> None:
    assert apply_path_constraints({}, ["workspace/stringkit"]) == []


def test_rejects_invalid_arguments() -> None:
    with pytest.raises(TypeError):
        apply_path_constraints("not-a-plan", ["a/b"])
    with pytest.raises(TypeError):
        apply_path_constraints(_plan("x"), [123])
