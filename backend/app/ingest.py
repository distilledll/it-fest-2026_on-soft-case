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
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace"), "utf-8-replace"


# Явные инъекции — достаточно одного совпадения.
INJECTION_RE = re.compile(
    r"(игнорир\w*|забудь\w*|ignore|disregard|system\s*prompt|ответь\s+что|отвечай\s+что"
    r"|инструкци\w+\s+для\s+(ии|модели|нейросет\w*|ассистент\w*)"
    r"|(для|при)\s+(целей\s+)?автоматизированн\w+\s+(анализ|обработк)\w*"
    r"|when\s+(you\s+are\s+)?asked|you\s+must\s+(answer|reply|say)|answer\s+that|assistant\s*:|<\|?im_start)",
    re.IGNORECASE,
)
# Упоминание ИИ само по себе законно (закупка чат-бота) — инъекция, только если рядом команда.
AI_MENTION_RE = re.compile(r"\b(ии|ai)\b|ии[-\s]?(ассистент|модел|агент)\w*|языков\w+\s+модел\w*|нейросет\w*"
                           r"|систем\w*\s+(автоматическ|искусственн)\w+\s+(обработк|интеллект)\w*", re.I)
COMMAND_RE = re.compile(r"\b(указыва\w*|укажи\w*|отвеча\w*|ответь|счита\w*|сообща\w*|называ\w*|пиши|выводи)\b", re.I)


def is_injection(text: str) -> bool:
    """Предложение похоже на инструкцию для ИИ, а не на условие закупки."""
    return bool(INJECTION_RE.search(text) or (AI_MENTION_RE.search(text) and COMMAND_RE.search(text)))


def has_injection(text: str) -> bool:
    return any(is_injection(s) for s in re.split(r"(?<=[.!?\n])", text))


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
    pdir = data_dir / "packages" / package
    return tuple(load_document(f, package) for f in sorted(pdir.glob("*.txt")))


def list_packages(data_dir: Path) -> list[str]:
    return sorted(p.name for p in (data_dir / "packages").iterdir() if p.is_dir())


def load_questions(data_dir: Path) -> list[Question]:
    text, _ = decode((data_dir / "questions.csv").read_bytes())
    return [Question(**{k.strip().lower(): (v or "").strip() for k, v in r.items()})
            for r in csv.DictReader(text.splitlines(), delimiter=";") if r.get("id")]
