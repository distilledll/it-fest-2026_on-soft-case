"""Общие типы. Это контракт между бэком, агентом и фронтом — менять только договорившись."""
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    ANSWER = "ответ"
    CONFLICT = "расхождение"
    ABSENT = "нет в документах"
    UNKNOWN = "не знаю"


class Question(BaseModel):
    id: str
    package: str
    question: str


class Document(BaseModel):
    package: str
    file: str
    text: str
    encoding: str
    is_empty: bool = False
    warnings: list[str] = Field(default_factory=list)  # напр. "подозрение на инструкцию в тексте"


class TraceStep(BaseModel):
    """Шаг агента — для показа на фронте «как система поймала обман»."""
    node: str                 # retrieve | answer | check_quote | critic_numbers | ...
    ok: bool | None = None
    message: str = ""
    data: dict = Field(default_factory=dict)


class Evidence(BaseModel):
    file: str
    quote: str
    value: str = ""


class Answer(BaseModel):
    id: str
    status: Status
    answer: str = ""
    quote: str = ""
    file: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    llm_calls: int = 0
    elapsed_s: float = 0.0
