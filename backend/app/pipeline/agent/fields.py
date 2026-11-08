"""Независимые извлекатели типовых полей закупки — «второе мнение» без модели.

Так делают системы обработки документов: у стандартных полей (НМЦК, обеспечение, сроки, дата подачи)
есть узнаваемые формулировки, и код находит кандидатов сам. Плюс проверочные правила между полями:
«обеспечение в рублях = процент × НМЦК». Если код уверенно нашёл одно значение, а модель ответила
другое, — это сигнал, сколь бы сильной или слабой ни была модель.

Кандидаты из старой редакции (изменённые пункты) и из инъекций отбрасываются.
"""
import re
from dataclasses import dataclass

from app.ingest import is_injection
from app.numwords import word_numbers
from app.schemas import Document
from app.verify import numbers

OLD_IN_AMEND = re.compile(r"[Пп]ункт\s+«[^»]*»")
NUM = r"(\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
SCALE = r"\s*(тыс\.?|млн\.?)?"


@dataclass
class Field:
    key: str
    title: str
    question: re.Pattern            # к какому вопросу относится поле
    patterns: list[re.Pattern]      # где значение: группы v (число), s (тыс./млн), d (дата), t (время)
    unit: str = ""


def _q(p: str) -> re.Pattern:
    return re.compile(p, re.I)


V = r"(?P<v>\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
S = r"\s*(?P<s>тыс\.?|млн\.?)?"
D = r"(?P<d>\d{2}\.\d{2}\.\d{4})"
T = r"(?P<t>\d{1,2}:\d{2})"
PAREN = r"\s*(?:\([^)]{1,40}\)\s*)?"

FIELDS = [
    Field("nmck", "НМЦК", _q(r"^(?!.*обеспечени).*(как\w*\s+(начальн|нмцк)|^\W*нмцк)"),
          [_q(r"начальн\w*\s*\(максимальн\w*\)\s*цен\w*\s*контракта\s*[:—–-]?\s*" + V + S + r"\s*руб")], "руб"),
    Field("contract_security_pct", "обеспечение исполнения, %", _q(r"обеспечени\w*\s+исполнени\w*.*процент"),
          [_q(r"обеспечени\w*\s+исполнени\w*\s+контракта[^.;%]{0,60}?" + V + r"\s*(?:%|процент)")], "%"),
    Field("bid_security_rub", "обеспечение заявки, руб", _q(r"обеспечени\w*\s+заявк\w*.*руб"),
          [_q(r"обеспечени\w*\s+заявк\w*[^.;]{0,80}?(?:составляет|—|-|:)\s*" + V + S + r"\s*руб")], "руб"),
    Field("deadline", "окончание подачи заявок", _q(r"до\s+какой\s+даты.*заявк|окончани\w*\s+срока\s+подачи"),
          [_q(r"окончани\w*\s+срока\s+подачи\s+заявок\s*[:—–-]?\s*" + D + r"\s+" + T),
           _q(r"заявки\s+принимаются\s+до\s+" + T + r"[^.;]{0,60}?" + D)]),
    Field("warranty_months", "гарантийный срок, мес", _q(r"гарантийн\w*\s+срок.*месяц"),
          [_q(r"гарантийн\w*\s+срок\w*\s+на\s+результат\w*\s+работ[^.;]{0,40}?" + V + PAREN + r"месяц"),
           _q(r"гаранти\w*\s+на\s+результат\w*[^.;]{0,30}?срок\w*\s*" + V + PAREN + r"месяц")], "мес"),
]


def _to_float(num: str, scale: str | None = None) -> float:
    v = numbers(num)[0] if numbers(num) else float("nan")
    if scale:
        v *= 1000 if scale.lower().startswith("тыс") else 1e6
    return round(v, 2)


def field_for(question: str) -> Field | None:
    return next((f for f in FIELDS if f.question.search(question)), None)


def candidates(field: Field, docs: list[Document], is_stale) -> list[tuple[str, str, str]]:
    """[(значение, файл, предложение)] — без старой редакции и инъекций. is_stale(sentence, file) -> bool."""
    out = []
    for d in docs:
        for sent in re.split(r"(?<=[.;])\s+|\n+", d.text):
            # в файле изменений старый текст стоит в «Пункт «…»» — его не считаем, берём только новую редакцию
            sent = OLD_IN_AMEND.sub(" ", sent)
            if not sent.strip() or is_injection(sent) or is_stale(sent, d.file):
                continue
            for m in (m for pat in field.patterns for m in pat.finditer(sent)):
                g = m.groupdict()
                if g.get("d"):
                    val = f"{g['d']} {g['t']}"
                else:
                    v = _to_float(g["v"], g.get("s"))
                    val = str(int(v)) if float(v).is_integer() else str(v)
                out.append((val, d.file, sent.strip()))
    return out


def answer_has(field: Field, value: str, answer: str) -> bool:
    if field.key == "deadline":
        date, time = value.split()
        return date in answer and time.replace(":", "") in re.sub(r"[:.]", "", answer)
    v = float(value)
    return any(abs(v - a) < 0.01 for a in numbers(answer) + word_numbers(answer))


SEC_EXEC_Q = re.compile(r"обеспечени\w*\s+исполнени", re.I)
BY_KEY = {f.key: f for f in FIELDS}


def unique(field: Field, docs: list[Document], is_stale) -> tuple[str, str] | None:
    """Значение поля, если код нашёл его однозначно: (значение, предложение)."""
    c = candidates(field, docs, is_stale)
    vals = {v for v, _, _ in c}
    return (c[0][0], c[0][2]) if len(vals) == 1 else None
