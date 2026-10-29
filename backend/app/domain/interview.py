"""Interview state. This structured state — not the chat transcript — is the
source of truth for what the user has confirmed."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.requirements import Conflict, RejectedSuggestion


class Option(BaseModel):
    value: str
    label: str
    description: str = ""


class QuestionView(BaseModel):
    id: str
    section: str = "general"
    prompt: str
    help: str  # plain-English explanation of the concept
    kind: Literal["choice", "number", "text"]
    options: list[Option] = Field(default_factory=list)
    recommended: str | None = None
    recommendation_reason: str | None = None
    affects: list[str] = Field(default_factory=list)
    unit: str | None = None


class Answer(BaseModel):
    question_id: str
    value: Any
    display: str
    # "user": chosen/typed explicitly; "accepted_recommendation": user clicked
    # the recommended option. Both count as confirmed by the user.
    origin: Literal["user", "accepted_recommendation"]
    answered_at: datetime
    raw_text: str | None = None
    interpreted_by: Literal["option", "deterministic_parser", "ai"] = "option"


class Hint(BaseModel):
    """Something detected in the free-text request. Never treated as confirmed."""

    key: str
    value: str
    evidence: str  # the phrase it was derived from
    detected_by: Literal["deterministic", "ai"]


class TranscriptEntry(BaseModel):
    role: Literal["user", "assistant", "system"]
    text: str
    at: datetime
    question_id: str | None = None
    kind: Literal["message", "question", "explanation", "warning", "clarification"] = "message"


class InterviewState(BaseModel):
    initial_request: str = ""
    hints: list[Hint] = Field(default_factory=list)
    answers: dict[str, Answer] = Field(default_factory=dict)
    rejected: list[RejectedSuggestion] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    current_question: str | None = None
    complete: bool = False
    engine: Literal["demo", "ai"] = "demo"
    ai_notes: list[str] = Field(default_factory=list)  # AI fallbacks, validation failures

    def value(self, qid: str, default: Any = None) -> Any:
        a = self.answers.get(qid)
        return a.value if a else default


class SectionProgress(BaseModel):
    id: str
    label: str
    description: str
    answered: int
    total: int
    current: bool = False


class InterviewView(BaseModel):
    state: InterviewState
    question: QuestionView | None
    progress: dict[str, int]
    applicable_questions: list[str]
    engine_label: str
    sections: list[SectionProgress] = Field(default_factory=list)
    # question id -> section id, for every applicable question
    question_sections: dict[str, str] = Field(default_factory=dict)
