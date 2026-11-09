"""Детерминированные проверки — последний рубеж перед записью ответа.
Работают поверх любого пайплайна: даже если агент ошибся, сюда не пролезет
выдуманная цитата или число, которого нет в цитате.
"""
from datetime import datetime, timedelta
import re

from rapidfuzz import fuzz

from app.ingest import is_injection, norm, redact
from app.numwords import NUMBER_PHRASE, word_numbers
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


DURATION_RE = re.compile(
    rf"(?<![\w.,])(\d+(?:[.,]\d+)?|{NUMBER_PHRASE})\s*"
    r"(?:\([^)]{1,30}\)\s*)?"
    r"(недел[а-яё]*|календарн[а-яё]*\s+(?:дн[а-яё]*|день))\b", re.I)


DAYS_24H_RE = re.compile(rf"\b(\d+(?:[.,]\d+)?|{NUMBER_PHRASE})\s+(?:сутки|суток|суткам|сутками)\b", re.I)


def calendar_days(quote: str) -> list[float]:
    return [word_numbers(amount)[0] * (7 if unit.lower().startswith("недел") else 1)
            for amount, unit in DURATION_RE.findall(quote)]


YEARS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:\([^)]{1,30}\)\s*)?(?:год\w*|лет)\b", re.I)


MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9,
          "окт": 10, "ноя": 11, "дек": 12}
MONTH_DATE_RE = re.compile(r"\b(\d{1,2})\s+(январ\w*|феврал\w*|март\w*|апрел\w*|ма[яй]|июн\w*|июл\w*|август\w*|"
                           r"сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)\s+(\d{4})", re.I)
SCALE_RE = re.compile(r"(\d+(?:[  ]\d{3})*(?:[.,]\d+)?)\s*(тыс\w*\.?|млн\.?|миллион\w*|млрд\.?)", re.I)
_SCALES = {"тыс": 1e3, "млн": 1e6, "мил": 1e6, "млр": 1e9}


def scaled_numbers(text: str) -> list[float]:
    return [round(numbers(m[1])[0] * _SCALES[m[2].lower()[:3]], 2) for m in SCALE_RE.finditer(text)]


def number_pool(text: str) -> list[float]:
    """Все числа фрагмента: цифрами, словами («пятидесяти тысяч»), с множителями («1 250 тыс. руб.»),
    и сроки в годах, пересчитанные в месяцы."""
    pool = numbers(text) + word_numbers(text) + calendar_days(text)
    for m in YEARS_RE.finditer(text or ""):
        pool.append(float(m.group(1).replace(",", ".")) * 12)
    for m in MONTH_DATE_RE.finditer(text or ""):
        day, month = int(m.group(1)), MONTHS[m.group(2).lower()[:3]]
        pool += [float(f"{day}.{month:02d}"), float(m.group(3))]
    pool.extend(scaled_numbers(text or ""))
    pool.extend(word_numbers(m[1])[0] * 24 for m in DAYS_24H_RE.finditer(text or ""))
    return pool


# Явно заданные смещения в условии подачи заявок позволяют проверить и смену даты.
UTC_OFFSET = r"UTC\s*([+-])(\d{1,2})(?::(\d{2}))?(?![\d:])"
LOCAL_SUBMISSION_ZONE = re.compile(
    r"время (?:подачи|при[её]ма) заявок[^.!?\n]{0,70}по местному времени[^.!?\n]{0,40}?" + UTC_OFFSET, re.I)
MOSCOW_ZONE = re.compile(r"московское время\s*[—–:=(-]*\s*" + UTC_OFFSET, re.I)
STAMP = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\s+(?:в\s+)?(\d{1,2}:\d{2})\b")


def moscow_deadline(question: str, quote: str, file: str, docs: list[Document]) -> str | None:
    """None — обычный вопрос; пустая строка — явный перевод, но источник неоднозначен."""
    if (not re.search(r"московск\w*\s+времен|по Москве", question, re.I) or "заяв" not in question.lower()
            or not re.search(r"подач|подава|при[её]м|принима", question, re.I)):
        return None
    doc = next((d for d in docs if d.file == file), None)
    if doc is None:
        return None
    text = redact(doc.text)[0]
    local = set(LOCAL_SUBMISSION_ZONE.findall(text))
    if not local:
        return None
    target = set(MOSCOW_ZONE.findall(text))
    stamps = set(STAMP.findall(quote))
    if len(local) != 1 or len(target) != 1 or len(stamps) != 1 or set(STAMP.findall(text)) != stamps:
        return ""
    delta = []
    for sign, hour, minute in (local.pop(), target.pop()):
        h, m = int(hour), int(minute or 0)
        if h > 14 or m > 59 or (h == 14 and m):
            return ""
        delta.append((1 if sign == "+" else -1) * (60 * h + m))
    date, time = stamps.pop()
    match = STAMP.search(text)
    tail = re.split(r"[.!?\n]", text[match.end():], maxsplit=1)[0]
    if re.search(r"московск|по Москве|UTC|\bМСК\b", tail, re.I):
        return ""  # У самой даты есть указание зоны, которое может менять общее правило.
    try:
        source = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")
        return (source + timedelta(minutes=delta[1] - delta[0])).strftime("%d.%m.%Y %H:%M")
    except (ValueError, OverflowError):
        return ""


def quote_exists(quote: str, docs: list[Document], file: str = "") -> Document | None:
    q = norm(quote)
    if len(q) < 8:
        return None
    matches = [d for d in docs if (not file or d.file == file) and q in norm(d.text)
               and q in norm(redact(d.text)[0])]
    return matches[0] if len(matches) == 1 else None


def snap_quote(quote: str, docs: list[Document], min_score: float = 90) -> tuple[str, str] | None:
    """Модель часто цитирует «почти дословно». Находим ближайший точный кусок текста
    и подменяем цитату на него. Возвращает (точная_цитата, файл) или None."""
    q = norm(quote)
    if len(q) < 8:
        return None
    best = None
    for d in docs:
        # ищем по предложениям/строкам — этого достаточно для документов закупок
        for frag in re.split(r"(?<=[.;:\n])\s+", redact(d.text)[0]):
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
        t = norm(redact(d.text)[0])
        i = t.find(q)
        if i >= 0:
            return t[max(0, i - width): i + len(q) + width]
    return q


def guard(ans: Answer, docs: list[Document], question: str = "", quote_only: bool = False) -> Answer:
    """Финальные правила. Если проверка не прошла и починить нельзя — честное «не знаю».
    quote_only=True — для движков, которые сами проверяют числа и расчёт кодом: цитата должна быть
    дословной (без подтягивания к похожему тексту — тот мог бы содержать другое число), числа не сверяем."""
    if ans.status in (Status.ABSENT, Status.UNKNOWN):
        return ans.model_copy(update={"answer": "", "quote": "", "file": "", "evidence": []})

    candidates = [d for d in docs if not ans.file or d.file == ans.file]
    doc = quote_exists(ans.quote, candidates)
    if doc is None:
        snapped = None
        if not quote_only and (ans.file or len(candidates) == 1):
            snapped = snap_quote(ans.quote, candidates)
        if snapped:
            ans.trace.append(TraceStep(node="guard_quote", ok=True, message="цитата поправлена до дословной",
                                       data={"was": ans.quote, "now": snapped[0]}))
            ans.quote, ans.file = snapped
            if not quote_exists(ans.quote, candidates, ans.file):
                return _unknown(ans)
        else:
            ans.trace.append(TraceStep(node="guard_quote", ok=False, message="цитаты нет в документах",
                                       data={"quote": ans.quote}))
            return _unknown(ans)
    elif doc.file != ans.file:
        ans.file = doc.file

    # Число из ответа должно встречаться в цитате — кроме вопросов-расчётов («сколько рублей составит»).
    is_calc = "составит" in question.lower()
    a_nums, q_nums = numbers(ans.answer), number_pool(nearby(ans.quote, docs, ans.file))
    for item in ans.evidence:
        if not quote_exists(item.quote, docs, item.file) or is_injection(item.quote):
            return _unknown(ans)
        q_nums.extend(number_pool(item.quote))
    a_nums.extend(scaled_numbers(ans.answer))
    converted = moscow_deadline(question, ans.quote, ans.file, docs)
    if converted is not None and ans.status == Status.ANSWER:
        return ans if converted and ans.answer.strip() == converted else _unknown(ans)
    if not quote_only and a_nums and not is_calc and ans.status == Status.ANSWER:
        if not all(any(abs(a - q) < 0.01 for q in q_nums) for a in a_nums):
            ans.trace.append(TraceStep(node="guard_number", ok=False, message="числа из ответа нет рядом с цитатой",
                                       data={"answer": a_nums, "quote": q_nums}))
            return _unknown(ans)
    return ans


def _unknown(ans: Answer) -> Answer:
    return ans.model_copy(update={"status": Status.UNKNOWN, "answer": "", "quote": "", "file": "", "evidence": []})
