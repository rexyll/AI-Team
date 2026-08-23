"""Prompt guidance contracts for planner role mapping and delivery usability.

The three systemic observations from real-provider runs (path constraints
dropped from plans, role semantic drift, and end-user usability blind spots)
are addressed through agent system prompts. These contracts pin the key
guidance clauses so they cannot silently disappear in later edits.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_planner_requires_explicit_constraint_propagation() -> None:
    content = _source("agents/planner.py")

    assert "用户需求中的显式约束必须逐条落实" in content
    assert "不得省略或改写" in content
    # Path-related constraints belong in the first implementation task.
    assert "第一个实现类任务" in content


def test_planner_pins_role_responsibility_boundaries() -> None:
    content = _source("agents/planner.py")

    # Test-case authoring belongs to developer, not tester.
    assert '"编写单元测试"类任务属于 developer' in content
    assert "不要给 tester 安排" in content
    # Reviewer judges; fixes loop back to developer.
    assert "reviewer 不执行修复" in content


def test_developer_requires_end_user_runnability_self_check() -> None:
    content = _source("agents/developer.py")

    assert "可运行性自检" in content
    assert "python -m" in content
    assert "用户运行交付物的确切命令" in content


def test_reviewer_checks_delivery_runnability() -> None:
    content = _source("agents/reviewer.py")

    assert "检查交付物的可运行性" in content
    assert "python -m" in content
