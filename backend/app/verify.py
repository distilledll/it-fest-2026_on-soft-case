"""Детерминированные проверки — последний рубеж перед записью ответа.
Работают поверх любого пайплайна: даже если агент ошибся, сюда не пролезет
выдуманная цитата или число, которого нет в цитате.
"""
import re

from rapidfuzz import fuzz

from app.ingest import norm
from app.numwords import word_numbers
from app.schemas import Answer, Document, Status, TraceStep

NUM_RE = re.compile(r"\d+(?:[   ]\d{3})*(?:[.,]\d+)?")


def numbers(s: str) -> list[float]:
    out = []
    for m in NUM_RE.findall(s or ""):
        try:
            out.append(float(re.sub(r"[   ]", "", m).replace(",", ".")))
        except ValueError:
            pass
    return out


YEARS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:\([^)]{1,30}\)\s*)?(?:год\w*|лет)\b", re.I)


MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9,
          "окт": 10, "ноя": 11, "дек": 12}
MONTH_DATE_RE = re.compile(r"\b(\d{1,2})\s+(январ\w*|феврал\w*|март\w*|апрел\w*|ма[яй]|июн\w*|июл\w*|август\w*|"
                           r"сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)\s+(\d{4})", re.I)
SCALE_RE = re.compile(r"(\d+(?:[  ]\d{3})*(?:[.,]\d+)?)\s*(тыс\w*\.?|млн\.?|миллион\w*|млрд\.?)", re.I)
_SCALES = {"тыс": 1e3, "млн": 1e6, "мил": 1e6, "млр": 1e9}


def number_pool(text: str) -> list[float]:
    """Все числа фрагмента: цифрами, словами («пятидесяти тысяч»), с множителями («1 250 тыс. руб.»),
    и сроки в годах, пересчитанные в месяцы."""
    pool = numbers(text) + word_numbers(text)
    for m in YEARS_RE.finditer(text or ""):
        pool.append(float(m.group(1).replace(",", ".")) * 12)
    for m in MONTH_DATE_RE.finditer(text or ""):
        day, month = int(m.group(1)), MONTHS[m.group(2).lower()[:3]]
        pool += [float(f"{day}.{month:02d}"), float(m.group(3))]
    for m in SCALE_RE.finditer(text or ""):
        base = numbers(m.group(1))
        if base:
            pool.append(round(base[0] * _SCALES[m.group(2).lower()[:3]], 2))
    return pool


def quote_exists(quote: str, docs: list[Document]) -> Document | None:
    q = norm(quote)
    if len(q) < 8:
        return None
    return next((d for d in docs if q in norm(d.text)), None)


def snap_quote(quote: str, docs: list[Document], min_score: float = 90) -> tuple[str, str] | None:
    """Модель часто цитирует «почти дословно». Находим ближайший точный кусок текста
    и подменяем цитату на него. Возвращает (точная_цитата, файл) или None."""
    q = norm(quote)
    if len(q) < 8:
        return None
    best = None
    for d in docs:
        # ищем по предложениям/строкам — этого достаточно для документов закупок
        for frag in re.split(r"(?<=[.;:\n])\s+", d.text):
            if len(frag.strip()) < 8:
                continue
            r = fuzz.partial_ratio_alignment(q, norm(frag))
            if r and r.score >= min_score and (best is None or r.score > best[0]):
                best = (r.score, norm(frag)[r.dest_start:r.dest_end], d.file)
    return (best[1], best[2]) if best else None


def nearby(quote: str, docs: list[Document], file: str = "", width: int = 250) -> str:
    """Окрестность цитаты в её файле (нормализованный текст). Короткая цитата «20.11.2026» —
    а время «09:00» стоит рядом в том же предложении; ответ при этом верный."""
    q = norm(quote)
    if not q:
        return ""
    ordered = sorted(docs, key=lambda d: d.file != file)
    for d in ordered:
        t = norm(d.text)
        i = t.find(q)
        if i >= 0:
            return t[max(0, i - width): i + len(q) + width]
    return q


def guard(ans: Answer, docs: list[Document], question: str = "") -> Answer:
    """Финальные правила. Если проверка не прошла и починить нельзя — честное «не знаю»."""
    if ans.status in (Status.ABSENT, Status.UNKNOWN):
        return ans

    doc = quote_exists(ans.quote, docs)
    if doc is None:
        snapped = snap_quote(ans.quote, docs)
        if snapped:
            ans.trace.append(TraceStep(node="guard_quote", ok=True, message="цитата поправлена до дословной",
                                       data={"was": ans.quote, "now": snapped[0]}))
            ans.quote, ans.file = snapped
        else:
            ans.trace.append(TraceStep(node="guard_quote", ok=False, message="цитаты нет в документах",
                                       data={"quote": ans.quote}))
            return _unknown(ans)
    elif doc.file != ans.file:
        ans.file = doc.file

    # Число из ответа должно встречаться в цитате — кроме вопросов-расчётов («сколько рублей составит»).
    is_calc = "составит" in question.lower()
    a_nums, q_nums = numbers(ans.answer), number_pool(nearby(ans.quote, docs, ans.file))
    if a_nums and not is_calc and ans.status == Status.ANSWER:
        if not any(abs(a - q) < 0.01 for a in a_nums for q in q_nums):
            ans.trace.append(TraceStep(node="guard_number", ok=False, message="числа из ответа нет рядом с цитатой",
                                       data={"answer": a_nums, "quote": q_nums}))
            return _unknown(ans)
    return ans


def _unknown(ans: Answer) -> Answer:
    return ans.model_copy(update={"status": Status.UNKNOWN, "answer": "", "quote": "", "file": ""})
