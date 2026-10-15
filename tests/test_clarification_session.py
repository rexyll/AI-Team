from __future__ import annotations

import pytest

from runtime.clarification_session import (
    ClarificationSession,
    parse_open_questions,
    prompt_for_answers,
    render_answers_document,
)


ANALYSIS = """# 需求规格说明（草案）

## 一、项目概述
词频工具。

## 二、功能需求清单
REQ-001 统计单词。

## 六、待确认问题
1. 是否需要支持中文分词？
2. 输入文件大小上限是多少？

## 五、假设与约束
-【假设】UTF-8 输入。
"""


def test_parse_open_questions_scopes_to_section():
    questions = parse_open_questions(ANALYSIS)

    assert questions == [
        "是否需要支持中文分词？",
        "输入文件大小上限是多少？",
    ]


def test_session_lifecycle_awaiting_to_clarified():
    session = ClarificationSession.create("统计词频", ANALYSIS)

    assert session.status == "awaiting_answers"
    assert len(session.questions) == 2
    assert session.unanswered() == [0, 1]

    session.record_answer(0, "不支持中文分词")
    assert session.status == "awaiting_answers"  # 1 of 2 answered

    session.record_answer(1, "100MB")
    assert session.status == "clarified"
    assert session.is_complete() is True


def test_record_answer_validates_index():
    session = ClarificationSession.create("统计词频", ANALYSIS)

    with pytest.raises(ValueError):
        session.record_answer(5, "x")
    with pytest.raises(TypeError):
        session.record_answer(0, None)


def test_answers_document_marks_deferred_questions():
    session = ClarificationSession.create("统计词频", ANALYSIS)
    session.record_answer(0, "按空格分词")

    document = session.answers_document()

    assert "按空格分词" in document
    assert "未答复——请继续保留相关假设" in document
    assert document.startswith("## 客户答复")


def test_prompt_loop_collects_and_skips():
    questions = ["Q1?", "Q2?", "Q3?"]
    responses = iter(["answer-1", "", "answer-3"])
    printed: list[str] = []

    answers = prompt_for_answers(
        questions,
        {},
        input_fn=lambda _prompt: next(responses),
        output_fn=printed.append,
    )

    assert answers == {0: "answer-1", 2: "answer-3"}


def test_prompt_loop_preserves_existing_answers():
    questions = ["Q1?", "Q2?"]

    answers = prompt_for_answers(
        questions,
        {0: "already-answered"},
        input_fn=lambda _prompt: "fresh-2",
        output_fn=lambda _line: None,
    )

    assert answers == {0: "already-answered", 1: "fresh-2"}


def test_session_save_load_round_trip(tmp_path):
    session = ClarificationSession.create("统计词频", ANALYSIS)
    session.record_answer(0, "不支持")
    path = session.save(tmp_path / "session.json")

    restored = ClarificationSession.load(path)

    assert restored.to_dict() == session.to_dict()
    assert restored.status == "awaiting_answers"


def test_load_rejects_incomplete_payload(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"session_id": "x"}', encoding="utf-8")

    with pytest.raises(ValueError, match="missing fields"):
        ClarificationSession.load(bad)
