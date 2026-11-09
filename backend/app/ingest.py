"""Загрузка закупок. Готовимся к «трудным файлам» из уровня со звёздочкой:
другая кодировка, пустой файл, инструкция внутри документа."""
import csv
import re
from functools import lru_cache
from pathlib import Path

from app.schemas import Document, Question


# Нормализация ровно как в check.py — цитаты сверяем тем же способом, что и оценщик.
def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е").replace(" ", " ").replace(" ", " ")
    s = re.sub("[«»„“”\"']", '"', s)
    s = re.sub("[–—−]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def decode(raw: bytes) -> tuple[str, str]:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            return raw.decode("utf-16", "replace"), "utf-16-replace"
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace"), "utf-8-replace"


# Явные инъекции — достаточно одного совпадения.
INJECTION_RE = re.compile(
    r"(\bигнорируй(?:те)?\b|игнорировать\s+(?:все|предыдущие)\s+инструкции|забудь(?:те)?\b|ignore|disregard|system\s*prompt|ответь\s+что|отвечай\s+что"
    r"|инструкци\w+\s+для\s+(ии|модели|нейросет\w*|ассистент\w*)"
    r"|when\s+(you\s+are\s+)?asked|you\s+must\s+(answer|reply|say)|answer\s+that|assistant\s*:|<\|?im_start)",
    re.IGNORECASE,
)
# Упоминание ИИ само по себе законно (закупка чат-бота) — инъекция, только если рядом команда.
AI_MENTION_RE = re.compile(r"(?:для|при)\s+(?:целей\s+)?автоматизированн\w+\s+(?:анализ|обработк)\w*|"
                           r"\b(ии|ai)\b|ии[-\s]?(ассистент|модел|агент)\w*|языков\w+\s+модел\w*|нейросет\w*"
                           r"|систем\w*\s+(автоматическ|искусственн)\w+\s+(обработк|интеллект)\w*", re.I)
COMMAND_RE = re.compile(
    r"\b(?:(?:указывай|укажи|отвечай|ответь|считай|сообщай|сообщи|называй|пиши|выводи)(?:те)?"
    r"|(?:следует|необходимо)\s+(?:считать|указывать|отвечать|сообщать|выводить))\b", re.I)


def is_injection(text: str) -> bool:
    """Предложение похоже на инструкцию для ИИ, а не на условие закупки."""
    return bool(INJECTION_RE.search(text) or (AI_MENTION_RE.search(text) and COMMAND_RE.search(text)))


def document_clauses(text: str) -> list[str]:
    return re.split(r"(?<=[.!?;])(?=\s|$)|(?<=\n)", text)


def redact(text: str) -> tuple[str, int]:
    """Предложения с инструкциями для ИИ заменяем пометкой. Возвращает (текст, сколько вырезано)."""
    n = 0
    out = []
    for s in document_clauses(text):
        if is_injection(s):
            n += 1
            out.append("[фрагмент удалён: похоже на инструкцию для ИИ, это не часть условий закупки]")
        else:
            out.append(s)
    return "".join(out), n


def has_injection(text: str) -> bool:
    return any(is_injection(s) for s in document_clauses(text))


# Только явно адресованная ИИ цитата, целиком занимающая отдельное предложение.
QUOTED_DIRECTIVE = re.compile(
    r'\s*«(?:подсказка|инструкция) для ИИ:\s*(?:ответь|отвечай|укажи)\b[^«»;]*»[.!?]?\s*', re.I)


def needs_redaction_review(text: str) -> bool:
    return any(is_injection(s) and not QUOTED_DIRECTIVE.fullmatch(s) for s in document_clauses(text))


def load_document(path: Path, package: str) -> Document:
    text, enc = decode(path.read_bytes())
    warnings = []
    if enc != "utf-8-sig":
        warnings.append(f"кодировка {enc}")
    if has_injection(text):
        warnings.append("подозрение на инструкцию для ИИ внутри документа")
    return Document(package=package, file=path.name, text=text, encoding=enc,
                    is_empty=not text.strip(), warnings=warnings)


@lru_cache
def load_package(data_dir: Path, package: str) -> tuple[Document, ...]:
    if not package or Path(package).name != package or package in (".", "..") or "\\" in package:
        raise ValueError("некорректное имя закупки")
    pdir = data_dir / "packages" / package
    if not pdir.is_dir():
        return ()
    return tuple(load_document(f, package) for f in sorted(pdir.iterdir()) if f.is_file() and f.suffix.lower() == ".txt")


def list_packages(data_dir: Path) -> list[str]:
    return sorted(p.name for p in (data_dir / "packages").iterdir() if p.is_dir())


def load_questions(data_dir: Path) -> list[Question]:
    text, _ = decode((data_dir / "questions.csv").read_bytes())
    return [Question(**{k.strip().lower(): (v or "").strip() for k, v in r.items()})
            for r in csv.DictReader(text.splitlines(), delimiter=";") if r.get("id")]
