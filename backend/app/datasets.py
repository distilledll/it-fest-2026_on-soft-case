"""Датасеты: встроенный "sample" + загруженные zip / отдельные файлы.

Раскладка на диске (как у организатора):
  <root>/packages/<P>/*.txt
  <root>/questions.csv        — необязательно (без него — только вопросы строкой ввода)
  <root>/answers_public.json  — необязательно (есть → прогон сразу оценивается check.py)
"""
import io
import json
import re
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from app.config import settings

ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")
SAFE_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)
MAX_FILES = 5000


class DatasetError(ValueError):
    pass


def path_of(dataset_id: str) -> Path:
    if dataset_id == "sample":
        if not (settings.sample_dir / "packages").is_dir():
            raise DatasetError("нет примера организатора: распакуйте архив в data/sample (см. data/README.md)")
        return settings.sample_dir
    if not ID_RE.match(dataset_id):
        raise DatasetError("плохой id датасета")
    p = settings.datasets_dir / dataset_id
    if not p.is_dir():
        raise DatasetError(f"нет датасета {dataset_id}")
    return p


def info(dataset_id: str) -> dict:
    root = path_of(dataset_id)
    meta_p = root / "dataset.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {"name": "Пример организатора"}
    pk = root / "packages"
    return {
        "id": dataset_id, **meta,
        "packages": sorted(p.name for p in pk.iterdir() if p.is_dir()) if pk.exists() else [],
        "has_questions": (root / "questions.csv").exists(),
        "has_gold": (root / "answers_public.json").exists(),
    }


def list_all() -> list[dict]:
    ids = ["sample"] if (settings.sample_dir / "packages").is_dir() else []
    if settings.datasets_dir.exists():
        ids += sorted((p.name for p in settings.datasets_dir.iterdir() if p.is_dir()), reverse=True)
    return [info(i) for i in ids]


def delete(dataset_id: str) -> None:
    if dataset_id == "sample":
        raise DatasetError("встроенный датасет удалить нельзя")
    shutil.rmtree(path_of(dataset_id))


def _new_dir(name: str) -> tuple[str, Path]:
    did = datetime.now().strftime("%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    d = settings.datasets_dir / did
    d.mkdir(parents=True)
    (d / "dataset.json").write_text(json.dumps(
        {"name": name, "created_at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False))
    return did, d


def _safe_parts(name: str) -> tuple[str, ...] | None:
    """Защита от zip-slip: только относительные пути без '..', служебный мусор пропускаем."""
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or any(x.startswith(("__MACOSX", ".")) for x in p.parts):
        return None
    return p.parts


def from_zip(data: bytes, name: str) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise DatasetError("файл не похож на zip") from e
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise DatasetError("слишком много файлов в архиве")
    if sum(i.file_size for i in infos) > settings.max_upload_mb * 4 * 2**20:
        raise DatasetError("архив слишком большой после распаковки")

    files: dict[tuple[str, ...], zipfile.ZipInfo] = {}
    for i in infos:
        if (i.external_attr >> 16) & 0o170000 == 0o120000:  # симлинк
            continue
        if parts := _safe_parts(i.filename):
            files[parts] = i

    # Корень — каталог, где лежит packages/ (в архиве организатора он вложен в папку).
    roots = {parts[:parts.index("packages")] for parts in files if "packages" in parts[:-1]}
    did, dest = _new_dir(name)
    try:
        if roots:
            root = min(roots, key=len)
            for parts, i in files.items():
                rel = parts[len(root):]
                if rel[:1] == ("packages",) and len(rel) == 3 and rel[2].lower().endswith(".txt"):
                    _write(dest / "packages" / rel[1] / rel[2], zf.read(i))
                elif len(rel) == 1 and rel[0] in ("questions.csv", "answers_public.json", "check.py"):
                    _write(dest / rel[0], zf.read(i))
        else:
            # Произвольный архив: папка с txt = закупка, txt в корне = закупка "P01".
            for parts, i in files.items():
                if not parts[-1].lower().endswith(".txt"):
                    continue
                pkg = parts[-2] if len(parts) >= 2 else "P01"
                _write(dest / "packages" / pkg / parts[-1], zf.read(i))
        if not (dest / "packages").exists():
            raise DatasetError("в архиве не нашлось .txt документов")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return did


def from_files(files: list[tuple[str, bytes]], name: str, package: str = "P01") -> str:
    """Загрузка отдельных .txt — одна закупка, вопросы будут строкой ввода."""
    did, dest = _new_dir(name)
    for fname, data in files:
        if fname.lower().endswith(".txt"):
            _write(dest / "packages" / package / _clean(fname), data)
        elif fname in ("questions.csv", "answers_public.json"):
            _write(dest / fname, data)
    if not (dest / "packages").exists():
        shutil.rmtree(dest)
        raise DatasetError("нужен хотя бы один .txt")
    return did


def _clean(name: str) -> str:
    return SAFE_NAME.sub("_", PurePosixPath(name.replace("\\", "/")).name)[:120] or "file.txt"


def _write(path: Path, data: bytes) -> None:
    path = path.parent / _clean(path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
