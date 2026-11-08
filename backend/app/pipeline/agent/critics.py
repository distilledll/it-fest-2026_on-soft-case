"""Узкие критики — проверки кодом, без модели. Каждый смотрит на одну ловушку.

Критик получает черновик ответа и документы, возвращает список Issue.
  error — ответ в таком виде отдавать нельзя: либо исправление, либо «не знаю»;
  warn  — подозрение: один повтор с подсказкой, дальше решает модель.
Набор критиков включается через ctx.options["critics"] — так меряем вклад каждого.
"""
import ast
import math
from collections import Counter
from contextvars import ContextVar
import operator
import re
from dataclasses import dataclass, field

from app.ingest import is_injection, norm
from app.schemas import Document
from app.numwords import word_numbers
from app.verify import nearby, number_pool, numbers, quote_exists, snap_quote


@dataclass
class Draft:
    status: str = "не знаю"
    answer: str = ""
    quote: str = ""
    file: str = ""
    evidence: list[dict] = field(default_factory=list)   # [{"file", "quote", "value"}] — все упоминания
    calc: str | None = None                               # "1800000 * 5 / 100" для вопросов-расчётов


@dataclass
class Issue:
    critic: str
    message: str
    severity: str = "error"   # error | warn
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------- тип вопроса

CALC_RE = re.compile(r"составит|рассчита|посчита|сколько\s+рублей.*если", re.IGNORECASE)
YESNO_RE = re.compile(r"да\s+или\s+нет", re.IGNORECASE)
NEGATION_RE = re.compile(
    r"\bне\s+(установлен\w*|требует\w*|предусмотрен\w*|применя\w*|предъявля\w*|нужн\w*|обязател\w*)|отсутству\w*|не\s+устанавлива\w*",
    re.IGNORECASE)
# «Положения раздела применяются, если иное не установлено…» — шаблонная фраза, не отрицание требования
NEGATION_NOISE_RE = re.compile(r"если\s+иное\s+не\s+(установлено|предусмотрено)", re.IGNORECASE)


def is_calc(question: str) -> bool:
    return bool(CALC_RE.search(question))


def is_yesno(question: str) -> bool:
    return bool(YESNO_RE.search(question))


def has_negation(text: str) -> bool:
    return bool(NEGATION_RE.search(NEGATION_NOISE_RE.sub("", text or "")))


# ---------------------------------------------------------------- изменения извещения

AMEND_ITEM_RE = re.compile(
    r"Пункт\s+«(?P<old>.+?)…?»\s*\((?P<file>[\w.\-]+)\)\s*изложить\s+в\s+следующей\s+редакции:\s*«(?P<new>.+?)»\s*\.?\s*$",
    re.IGNORECASE | re.MULTILINE)


@dataclass
class Amendment:
    amend_file: str
    target_file: str
    old_prefix: str
    new_text: str
    old_sentence: str = ""     # полное старое предложение из целевого файла (если нашли)
    repealed: bool = False     # пункт признан утратившим силу — требования больше нет
    clause: str = ""           # номер пункта, если изменение ссылается на номер


AMEND_NUM_RE = re.compile(
    r"[Пп]ункт\s+(?P<num>\d+(?:\.\d+)+)\.?\s*(?:извещения\s*)?(?:\((?P<file>[\w.\-]+)\)\s*)?[^«\n]{0,80}?"
    r"изложить\s+в\s+(?:следующей|новой)\s+редакции:?\s*«(?P<new>.+?)»", re.M)
REPEAL_RE = re.compile(
    r"[Пп]ункт\s+(?P<num>\d+(?:\.\d+)+)\.?\s*(?:извещения\s*)?(?:\((?P<file>[\w.\-]+)\)\s*)?[^\n]{0,80}?"
    r"(?:признать|считать)\s+утратившим\s+силу", re.M)


def _notice_file(docs: list[Document]) -> str | None:
    return next((d.file for d in docs if "izveshch" in d.file.lower() and not is_amendment_doc(d)), None)


def _clause_sentence(text: str, num: str) -> str:
    for sent in _sentences(text):
        if re.match(rf"\s*{re.escape(num)}\.?\s", sent):
            return sent
    return ""


def is_amendment_doc(d: Document) -> bool:
    return "izmenen" in d.file.lower() or norm(d.text[:200]).startswith("изменения извещения")


def parse_amendments(docs: list[Document]) -> list[Amendment]:
    by_file = {d.file: d for d in docs}
    out = []
    for d in docs:
        if not is_amendment_doc(d):
            continue
        for m in AMEND_ITEM_RE.finditer(d.text):
            a = Amendment(d.file, m["file"], m["old"].rstrip("…. "), m["new"].strip())
            target = by_file.get(a.target_file)
            if target:
                prefix = norm(a.old_prefix)
                for sent in _sentences(target.text):
                    if prefix and prefix in norm(sent):
                        a.old_sentence = sent
                        break
            out.append(a)
        for m in AMEND_NUM_RE.finditer(d.text):
            target = m["file"] or _notice_file(docs)
            old_sent = _clause_sentence(by_file[target].text, m["num"]) if target in by_file else ""
            out.append(Amendment(d.file, target or "", old_sent[:80], m["new"].strip(), old_sent, clause=m["num"]))
        for m in REPEAL_RE.finditer(d.text):
            target = m["file"] or _notice_file(docs)
            old_sent = _clause_sentence(by_file[target].text, m["num"]) if target in by_file else ""
            out.append(Amendment(d.file, target or "", old_sent[:80], "", old_sent, repealed=True, clause=m["num"]))
    return out


def superseded_by(quote: str, file: str, amendments: list[Amendment]) -> Amendment | None:
    """Цитата взята из старой редакции? Старая редакция — это пункт в исходном файле (в том числе
    вместе с номером «2.5. …») или текст после «Пункт «…»» внутри самого файла изменений."""
    q = norm(quote)
    if not q:
        return None
    for a in amendments:
        prefix, old, new = norm(a.old_prefix), norm(a.old_sentence), norm(a.new_text)
        if file != a.amend_file:
            if old and (q in old or old in q):
                return a
            if len(prefix) >= 15 and prefix in q:
                return a
        else:
            if q in prefix and q not in new:
                return a
            if len(prefix) >= 15 and prefix in q and new not in q:
                return a
    return None


CLAUSE_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)+\.?\s*")
CLAUSE_REF = re.compile(r"(?:[Пп]ункт\w*|п\.|раздел\w*|приложени\w*)\s*№?\s*\d+(?:\.\d+)*", re.I)


def _strip_refs(text: str) -> str:
    """Убираем номера пунктов: «2.6. Требование…», «Пункт 2.6 извещения…» — это не значения параметра."""
    return CLAUSE_REF.sub(" ", CLAUSE_PREFIX.sub("", text or ""))
CLAUSE_NO = re.compile(r"^\d+(?:\.\d+)*\.?$")


def _sentences(text: str) -> list[str]:
    """Предложения; номер пункта («2.5.») не отрывается от текста пункта."""
    out: list[str] = []
    for part in re.split(r"(?<=[.;])\s+|\n+", text):
        if not part.strip():
            continue
        if out and CLAUSE_NO.match(out[-1].strip()):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


# ---------------------------------------------------------------- критики

def critic_quote(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """Цитата должна дословно быть в документах. Почти дословную подтягиваем к точному тексту."""
    if d.status in ("нет в документах", "не знаю"):
        return []
    if len(norm(d.quote)) < 8:
        return [Issue("quote", "нет цитаты или она короче 8 символов — приведи дословный фрагмент документа")]
    doc = quote_exists(d.quote, docs)
    if doc:
        d.file = doc.file
        return []
    snapped = snap_quote(d.quote, docs)
    if snapped:
        d.quote, d.file = snapped
        return []
    return [Issue("quote", f"цитаты «{d.quote[:120]}» нет в документах — скопируй фрагмент дословно",
                  data={"quote": d.quote})]


# опция multipart: числа ответа можно подтверждать любой проверенной цитатой из evidence (вопросы из нескольких
# частей, где части в разных местах документов). ContextVar — чтобы параллельные вопросы не мешали друг другу.
MULTIPART_CTX: ContextVar[bool] = ContextVar("multipart", default=True)


def critic_number(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """Каждое число из ответа должно быть в цитате или рядом с ней в том же месте документа
    (для расхождения и вопросов из нескольких частей — ещё и в подтверждённых evidence)."""
    if d.status not in ("ответ", "расхождение") or is_calc(question):
        return []
    a_nums = numbers(d.answer)
    if not a_nums:
        return []
    around = nearby(d.quote, docs, d.file)
    pool = number_pool(around)
    if d.status == "расхождение" or MULTIPART_CTX.get():
        for e in d.evidence:
            if quote_exists(e.get("quote", ""), docs):
                ev = nearby(e["quote"], docs, e.get("file", ""))
                pool += number_pool(ev)
    missing = [a for a in a_nums if not any(abs(a - p) < 0.01 for p in pool)]
    if missing and d.status == "расхождение":
        return [Issue("number", f"для значений {missing} нет подтверждающей цитаты — добавь в evidence "
                                f"дословную цитату для каждого значения расхождения", data={"missing": missing})]
    if missing:
        hint = " (если вопрос из нескольких частей — приведи в evidence цитату на каждую часть)" if MULTIPART_CTX.get() else ""
        return [Issue("number", f"чисел {missing} нет в цитате «{d.quote[:120]}» — возьми число из цитаты "
                                f"или приведи цитату, где оно есть{hint}", data={"missing": missing})]
    return []


def critic_amendment(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """Значение изменили в изменениях извещения — верна только новая редакция."""
    if not amendments or d.status in ("нет в документах", "не знаю"):
        return []
    a = superseded_by(d.quote, d.file, amendments)
    if a and a.repealed:
        return [Issue("amendment",
                      f"цитата из пункта {a.clause}, который признан утратившим силу в {a.amend_file} — этого требования "
                      f"больше нет. Ответь «не требуется» и процитируй фразу об утрате силы",
                      data={"old": a.old_sentence, "file": a.amend_file, "repealed": True})]
    if a:
        return [Issue("amendment",
                      f"цитата из старой редакции, этот пункт изменён в {a.amend_file}. "
                      f"Новая редакция: «{a.new_text}». Ответь по ней и процитируй её",
                      data={"old": a.old_sentence or a.old_prefix, "new": a.new_text, "file": a.amend_file})]
    if d.status == "расхождение":
        # расхождение «старая редакция vs новая» — это не расхождение, а изменение
        olds = [e for e in d.evidence if superseded_by(e.get("quote", ""), e.get("file", ""), amendments)]
        if olds:
            return [Issue("amendment", "одно из значений взято из пункта, который изменён в изменениях извещения — "
                                       "это не расхождение, верна новая редакция", data={"stale": olds})]
    return []


def critic_conflict(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """Извещение и контракт противоречат друг другу? Сверяем значения из всех найденных упоминаний."""
    if d.status in ("нет в документах", "не знаю") or is_calc(question):
        return []
    live = []
    for e in d.evidence:
        q, f = e.get("quote", ""), e.get("file", "")
        if not quote_exists(q, docs) or superseded_by(q, f, amendments) or is_injection(nearby(q, docs, f, width=80)):
            continue
        # значение — из поля value; из цитаты только без номера пункта («2.6. Требование…» — не значение 2.6)
        nums = numbers(_strip_refs(e.get("value", ""))) or numbers(_strip_refs(q))
        if nums:
            live.append((f, nums[0], q, str(e.get("part") or "1")))
    distinct = {v for _, v, _, _ in live}
    files = {f for f, _, _, _ in live}
    if d.status == "ответ" and len(distinct) > 1 and len(files) > 1:
        # сравниваем только упоминания одной и той же части вопроса (вопрос из нескольких частей — не расхождение)
        groups: dict[str, list] = {}
        for row in live:
            groups.setdefault(row[3], []).append(row)
        a_nums = numbers(d.answer)
        answered_all = all(any(abs(v - a) < 0.01 for a in a_nums) for v in distinct)
        for rows in groups.values():
            vals, fls = {r[1] for r in rows}, {r[0] for r in rows}
            if len(vals) < 2 or len(fls) < 2:
                continue
            if len(groups) == 1 and MULTIPART_CTX.get() and answered_all and ";" in d.answer:
                continue   # части не размечены, но ответ уже содержит все значения по частям
            desc = "; ".join(f"{v:g} в {f} («{q[:60]}»)" for f, v, q, _ in rows)
            return [Issue("conflict", f"в документах разные значения: {desc}. Если это один и тот же параметр — "
                                      f"статус «расхождение» и оба значения в answer", severity="warn",
                          data={"values": sorted(vals)})]
    if d.status == "расхождение":
        a_nums = set(numbers(d.answer))
        if len(a_nums) < 2:
            return [Issue("conflict",
                          "расхождение — это когда ОДИН И ТОТ ЖЕ параметр (срок, сумма, процент, дата) в разных файлах "
                          "имеет разные значения, например «60 и 75». Если упоминания про разные требования или одно из "
                          "них — отрицание («не установлено»), это не расхождение: ответь статусом «ответ». "
                          "Если расхождение есть — в answer должны быть оба значения цифрами")]
        if live and len(distinct) < 2:
            return [Issue("conflict", "найденные упоминания совпадают — расхождения нет, проверь ещё раз",
                          severity="warn")]
    return []


def critic_negation(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """«Требования нет»: слово встречается, но документ прямо говорит, что требование не установлено."""
    if d.status != "ответ":
        return []
    neg = has_negation(d.quote)
    ans = norm(d.answer)
    says_yes = re.search(r"\bда\b", ans) is not None
    if says_yes and neg:
        return [Issue("negation", f"в цитате «{d.quote[:120]}» требование отрицается, а ответ «да»")]
    if neg and numbers(d.answer) and not is_calc(question) and not numbers(d.quote):
        return [Issue("negation", "цитата говорит, что требования нет, а в ответе число — "
                                  "ответь «не требуется» / «не установлено»")]
    return []


def critic_calc(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """Расчёты считает код, не модель: проверяем выражение и подставляем результат."""
    if not is_calc(question) or d.status != "ответ":
        return []
    if not d.calc:
        return [Issue("calc", "это вопрос-расчёт: заполни поле calc арифметическим выражением из чисел документа, "
                              "например \"1800000 * 5 / 100\"")]
    try:
        value, operands = safe_eval(d.calc)
    except ValueError as e:
        return [Issue("calc", f"не могу вычислить calc «{d.calc}»: {e}")]
    doc_nums = set(numbers(" ".join(x.text for x in docs))) | {100.0}
    stale_nums = set()
    for a in amendments:
        stale_nums |= set(numbers(a.old_sentence or a.old_prefix)) - set(numbers(a.new_text))
    unknown = [o for o in operands if not any(abs(o - n) < 0.01 for n in doc_nums)]
    if unknown:
        return [Issue("calc", f"чисел {unknown} из calc нет в документах")]
    stale = [o for o in operands if o in stale_nums and o != 100]
    if stale:
        return [Issue("calc", f"в расчёте устаревшие значения {stale} — они изменены в изменениях извещения")]
    if not any(abs(value - n) < 0.01 for n in numbers(d.answer)):
        d.answer = _fmt(value)  # исправляем сами: результат считает код
    return []


# Только сроки: на деньгах и процентах слишком много соседних параметров (обеспечение заявки vs контракта).
UNIT_RE = re.compile(r"\d[\d  ]*\)?\s*(?:\([^)]{1,40}\)\s*)?(календарн\w*\s+дн\w*|рабоч\w*\s+дн\w*|месяц\w*)", re.IGNORECASE)
STOP_STEMS = {"какой", "какая", "каков", "сколь", "должн", "нужно", "ответ", "рубля", "проце", "кален", "днях", "дней",
              "месяц", "минима", "макси", "котор", "если", "цене", "участ"}


def _stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in re.findall(r"[а-яё]{4,}", text, re.IGNORECASE)} - STOP_STEMS


def _quote_sentence(d: Draft, docs: list[Document]) -> str:
    q = norm(d.quote)
    for doc in sorted(docs, key=lambda x: x.file != d.file):
        for sent in _sentences(doc.text):
            if q and q in norm(sent):
                return sent
    return d.quote


def critic_crosscheck(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """Сверка кодом, без опоры на evidence от модели: ищем в документах другие предложения про тот же
    параметр (та же единица измерения + те же редкие слова вопроса) с другим числом. Ловит пропущенное
    расхождение. Похожесть — с весами по редкости слов (IDF): «результаты работ», «документ о приёмке»
    весят больше, чем «заказчик» и «рабочих дней», поэтому соседние пункты-отвлекалки не цепляются."""
    if d.status != "ответ" or is_calc(question) or is_yesno(question):
        return []
    a_nums = numbers(d.answer)
    if not a_nums:
        return []
    m = UNIT_RE.search(nearby(d.quote, docs, d.file, width=60))
    if not m:
        return []
    unit = m.group(1).lower()[:5]   # «кален» / «рабоч» / «месяц» — календарные и рабочие дни не смешиваем
    q_stems = _stems(question)
    if not q_stems:
        return []
    sents = [(doc.file, sent) for doc in docs for sent in _sentences(doc.text)]
    df = Counter(st for _, sent in sents for st in _stems(sent) & q_stems)
    idf = {st: math.log((len(sents) + 1) / (df.get(st, 0) + 1)) + 0.1 for st in q_stems}

    def weight(text: str) -> float:
        return sum(idf[st] for st in _stems(text) & q_stems)

    base = weight(_quote_sentence(d, docs))
    if base <= 0:
        return []
    found = []
    for file, sent in sents:
        if (superseded_by(sent, file, amendments) or is_injection(sent)
                or any(norm(sent) in norm(a.old_prefix) for a in amendments)):
            continue
        um = [x for x in UNIT_RE.finditer(sent) if x.group(1).lower()[:5] == unit]
        if not um or weight(sent) < 0.8 * base:
            continue
        vals = [v for x in um for v in numbers(_words_to_digits(x.group(0))) + numbers(x.group(0))]
        other = [v for v in vals if not any(abs(v - a) < 0.01 for a in a_nums)]
        if other and not any(abs(v - a) < 0.01 for v in vals for a in a_nums):
            found.append((file, other[0], sent.strip()[:160]))
    if found:
        desc = "; ".join(f"{v:g} в {f}: «{s}»" for f, v, s in found[:3])
        return [Issue("crosscheck", f"в документах есть другие значения этого параметра: {desc}. Если это тот же "
                                    f"параметр — статус «расхождение», оба значения в answer и цитаты в evidence",
                      severity="warn", data={"found": found[:3]})]
    return []


QUANT_Q = re.compile(r"\b(сколько|скольких|какой\s+(размер|срок|объ[её]м|процент|минимальн)|какая\s+(цена|сумма|"
                     r"начальн|минимальн)|какое\s+количество)|в\s+(рублях|процентах|месяцах|днях|календарных|рабочих)", re.I)
DATE_Q = re.compile(r"до\s+какой\s+даты|какая\s+дата|какого\s+числа", re.I)
NEG_ANSWER = re.compile(r"\bнет\b|\bне\s+(требует|установлен|предусмотрен|предъявля|устанавлива|нужн)|отсутству|утратил",
                        re.I)


def critic_shape(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """Форма ответа совпадает с вопросом: «сколько / какой размер» → число, «до какой даты» → дата,
    «да или нет» → да/нет. Иначе модель отвечает словами из документа («в количестве, достаточном…»)
    там, где ответа нет — это обман."""
    if d.status != "ответ":
        return []
    ans = d.answer or ""
    if NEG_ANSWER.search(ans):
        return []
    if is_yesno(question):
        if not re.search(r"\b(да|нет)\b", norm(ans)):
            return [Issue("shape", "вопрос «да или нет», а в ответе нет ни «да», ни «нет»")]
        return []
    if DATE_Q.search(question) and not re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", ans):
        return [Issue("shape", "вопрос о дате, а в ответе нет даты в виде ДД.ММ.ГГГГ. Если даты в документах нет — "
                               "status «нет в документах»")]
    if QUANT_Q.search(question) and not number_pool(ans):
        return [Issue("shape", "вопрос о количестве, сумме или сроке, а в ответе нет числа. Если конкретного числа в "
                               "документах нет — status «нет в документах»; если требования нет — «не требуется»")]
    return []


def critic_fields(d: Draft, docs: list[Document], question: str, amendments: list[Amendment]) -> list[Issue]:
    """Второе мнение без модели: извлекатели типовых полей (НМЦК, обеспечение, срок, дата, гарантия)
    и проверочное правило «обеспечение исполнения в рублях = процент × НМЦК»."""
    from app.pipeline.agent import fields as F

    def stale(sent: str, file: str) -> bool:
        return superseded_by(sent, file, amendments) is not None

    if is_calc(question):
        if d.status != "ответ" or not F.SEC_EXEC_Q.search(question):
            return []
        nmck, pct = F.unique(F.BY_KEY["nmck"], docs, stale), F.unique(F.BY_KEY["contract_security_pct"], docs, stale)
        if not (nmck and pct):
            return []
        expected = round(float(nmck[0]) * float(pct[0]) / 100, 2)
        if not any(abs(expected - a) < 0.01 for a in numbers(d.answer)):
            return [Issue("fields", f"по документам НМЦК {nmck[0]} × {pct[0]} % = {_fmt(expected)} руб. "
                                    f"(«{nmck[1][:70]}», «{pct[1][:70]}»), а в ответе {d.answer}",
                          data={"expected": expected})]
        return []
    field = F.field_for(question)
    if not field or d.status == "не знаю":
        return []
    cands = F.candidates(field, docs, stale)
    vals = {v for v, _, _ in cands}
    if len(vals) == 1:
        v, file, sent = cands[0]
        if d.status == "нет в документах":
            return [Issue("fields", f"в документах есть {field.title}: {v} («{sent[:120]}», {file}) — ответ есть",
                          severity="warn", data={"value": v, "file": file})]
        if d.status == "ответ" and not F.answer_has(field, v, d.answer):
            return [Issue("fields", f"код нашёл в документах {field.title}: {v} («{sent[:120]}», {file}), "
                                    f"а в ответе «{d.answer}» — проверь", severity="warn",
                          data={"value": v, "file": file})]
    elif len(vals) > 1 and d.status == "ответ" and len({f for _, f, _ in cands}) > 1:
        desc = "; ".join(f"{v} в {f} («{s_[:60]}»)" for v, f, s_ in cands[:4])
        return [Issue("fields", f"код нашёл разные значения поля «{field.title}»: {desc}. Возможно, это расхождение",
                      severity="warn", data={"values": sorted(vals)})]
    return []


CRITICS = {
    "quote": critic_quote,
    "number": critic_number,
    "amendment": critic_amendment,
    "conflict": critic_conflict,
    "crosscheck": critic_crosscheck,
    "negation": critic_negation,
    "calc": critic_calc,
    "shape": critic_shape,
    "fields": critic_fields,
}


def run_critics(d: Draft, docs: list[Document], question: str, enabled: list[str] | None = None) -> list[Issue]:
    amendments = parse_amendments(docs)
    issues = []
    for name, fn in CRITICS.items():
        if enabled is None or name in enabled:
            issues += fn(d, docs, question, amendments)
    return issues


# ---------------------------------------------------------------- утилиты

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def safe_eval(expr: str) -> tuple[float, list[float]]:
    """Только числа, + - * / и скобки. Возвращает (результат, операнды)."""
    expr = re.sub(r"(?<=\d)[  ](?=\d{3})", "", expr).replace(",", ".").replace("×", "*").replace("%", "/100")
    operands: list[float] = []

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            operands.append(float(n.value))
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        raise ValueError("разрешены только числа и + - * /")

    try:
        return ev(ast.parse(expr, mode="eval")), operands
    except (SyntaxError, ZeroDivisionError) as e:
        raise ValueError(str(e)) from e


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if v % 1 else str(int(v))


def _words_to_digits(s: str) -> str:
    """Для совместимости: числа словами как строка цифр (используется в разборе сроков)."""
    return " ".join(str(int(v)) if float(v).is_integer() else str(v) for v in word_numbers(s))
