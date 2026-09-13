"""Interactive clarification session state machine.

Bridges the gap between "customer drops a one-line requirement" and "team
delivers": the analyst's draft spec carries 【待确认问题】 (open questions);
this module turns that artifact into a resumable session —

    awaiting_answers → clarified → delivered

The customer answers questions interactively (terminal prompt loop with
injectable I/O) or by editing the saved session file; the answers document
feeds the analyst as authoritative clarifications. Sessions are plain JSON,
so a run can be paused on one machine and resumed later.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_SESSION_STATUS_AWAITING = "awaiting_answers"
_SESSION_STATUS_CLARIFIED = "clarified"
_SESSION_STATUS_DELIVERED = "delivered"


def parse_open_questions(analysis: str) -> list[str]:
    """Extract open questions from the analyst draft's 待确认问题 section."""
    if not isinstance(analysis, str):
        raise TypeError("analysis must be a string")

    questions: list[str] = []
    in_section = False
    for line in analysis.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = "待确认问题" in stripped
            continue
        if not in_section or not stripped:
            continue
        text = stripped.lstrip("-*").strip()
        text = re.sub(r"^\d+[.、）)]\s*", "", text)
        if text:
            questions.append(text)
    return questions


def render_answers_document(
    questions: list[str],
    answers: dict[int, str],
    *,
    include_unanswered: bool = True,
) -> str:
    """Render the authoritative clarification document for the analyst.

    Answered questions carry their answers; unanswered ones are listed as
    explicitly deferred so the analyst keeps the corresponding assumptions.
    """
    lines = ["## 客户答复（权威，优先级最高）", ""]
    for index, question in enumerate(questions):
        answer = answers.get(index, "").strip()
        lines.append(f"{index + 1}. 问题：{question}")
        if answer:
            lines.append(f"   答复：{answer}")
        elif include_unanswered:
            lines.append("   答复：（未答复——请继续保留相关假设）")
    return "\n".join(lines) + "\n"


def prompt_for_answers(
    questions: list[str],
    answers: dict[int, str],
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> dict[int, str]:
    """Interactively prompt for one answer per unanswered question.

    I/O is injectable for tests. An empty answer skips the question
    (the analyst keeps the corresponding assumption).
    """
    # Session answers use string keys (JSON round trip); normalize here.
    resolved = {int(key): value for key, value in answers.items()}
    for index, question in enumerate(questions):
        if index in resolved and resolved[index].strip():
            continue
        output_fn(f"\n[{index + 1}/{len(questions)}] {question}")
        answer = input_fn("答复（回车跳过）: ").strip()
        if answer:
            resolved[index] = answer
        else:
            output_fn("  -> 已跳过；将保留相关假设。")
    return resolved


@dataclass
class ClarificationSession:
    """Resumable clarification state for one customer requirement."""

    session_id: str
    requirement: str
    status: str
    questions: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)  # key = str(index)
    analysis: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.created_at = self.created_at or now
        self.updated_at = self.updated_at or now

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def create(cls, requirement: str, analysis: str) -> "ClarificationSession":
        questions = parse_open_questions(analysis)
        return cls(
            session_id=uuid.uuid4().hex,
            requirement=requirement,
            status=_SESSION_STATUS_AWAITING,
            questions=questions,
            analysis=analysis,
        )

    def record_answer(self, index: int, answer: str) -> None:
        if not isinstance(answer, str):
            raise TypeError("answer must be a string")
        if index < 0 or index >= len(self.questions):
            raise ValueError(f"question index out of range: {index}")
        self.answers[str(index)] = answer
        self._refresh_status()

    def unanswered(self) -> list[int]:
        return [i for i in range(len(self.questions)) if not self.answers.get(str(i), "").strip()]

    def is_complete(self) -> bool:
        return bool(self.questions) and not self.unanswered()

    def mark_delivered(self) -> None:
        self.status = _SESSION_STATUS_DELIVERED
        self._touch()

    def answers_document(self) -> str:
        answers = {int(key): value for key, value in self.answers.items()}
        return render_answers_document(self.questions, answers)

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "requirement": self.requirement,
            "status": self.status,
            "questions": list(self.questions),
            "answers": dict(self.answers),
            "analysis": self.analysis,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClarificationSession":
        if not isinstance(payload, dict):
            raise TypeError("session payload must be a dictionary")
        required = {"session_id", "requirement", "status", "questions"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"session missing fields: {sorted(missing)}")
        return cls(
            session_id=payload["session_id"],
            requirement=payload["requirement"],
            status=payload["status"],
            questions=list(payload["questions"]),
            answers={str(k): str(v) for k, v in (payload.get("answers") or {}).items()},
            analysis=payload.get("analysis") or "",
            created_at=payload.get("created_at") or "",
            updated_at=payload.get("updated_at") or "",
        )

    def save(self, path: str | Path) -> Path:
        self._touch()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    @classmethod
    def load(cls, path: str | Path) -> "ClarificationSession":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    # -- internal -----------------------------------------------------------

    def _refresh_status(self) -> None:
        if self.status == _SESSION_STATUS_DELIVERED:
            return
        self.status = (
            _SESSION_STATUS_CLARIFIED
            if self.is_complete()
            else _SESSION_STATUS_AWAITING
        )
        self._touch()

    def _touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
