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


def checker_for(data_dir: Path) -> tuple[Path, str]:
    """Все наборы оцениваются установленным оценщиком организатора."""
    return settings.checker, "эталонный (backend/eval/check.py)"


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
        "checker": checker_for(root)[1],
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
            if parts in files:
                raise DatasetError(f"повторяющийся путь в архиве: {i.filename}")
            files[parts] = i

    # Корень — каталог, где лежит packages/ (в архиве организатора он вложен в папку).
    roots = {parts[:parts.index("packages")] for parts in files if "packages" in parts[:-1]}
    did, dest = _new_dir(name)
    try:
        if roots:
            if len(roots) != 1:
                raise DatasetError("в архиве несколько каталогов packages; загрузите один набор")
            root = roots.pop()
            for parts, i in files.items():
                if parts[:len(root)] != root:
                    continue
                rel = parts[len(root):]
                if rel[:1] == ("packages",) and len(rel) == 3 and rel[2].lower().endswith(".txt"):
                    _write(dest / "packages" / rel[1] / rel[2], zf.read(i))
                elif len(rel) == 1 and (std := standard_name(rel[0])):
                    # questions_control.csv → questions.csv; точное имя важнее, если в архиве оба
                    if not (dest / std).exists() or rel[0] == std:
                        _write(dest / std, zf.read(i))
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


def standard_name(name: str) -> str | None:
    """Под каким стандартным именем хранить служебный файл набора. Организатор называет файлы по-разному:
    questions.csv, questions_control.csv; answers_public.json, answers_control.json."""
    low = name.lower()
    if low.endswith(".csv") and low.startswith("questions"):
        return "questions.csv"
    if low.endswith(".json") and low.startswith("answers"):
        return "answers_public.json"
    return None


def set_gold(dataset_id: str, data: bytes) -> dict:
    """Эталон (answers_public.json) для набора, загруженного без ответов, — например, контрольного:
    организатор может выдать ответы после сдачи. Прогоны набора после этого можно пересчитать."""
    from app.ingest import load_questions
    if dataset_id == "sample":
        raise DatasetError("эталон примера организатора менять нельзя")
    root = path_of(dataset_id)
    try:
        gold = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise DatasetError(f"файл эталона — не JSON: {e}")
    need = ("id", "status", "type", "kind", "expected")
    if not isinstance(gold, list) or not gold or not all(isinstance(g, dict) and all(k in g for k in need)
                                                           for g in gold):
        raise DatasetError("ожидается answers_public.json в формате организатора: список объектов с полями "
                           + ", ".join(need))
    qids = {q.id for q in load_questions(root)} if (root / "questions.csv").exists() else set()
    gids = {str(g["id"]) for g in gold}
    if qids and (unknown := sorted(gids - qids)):
        raise DatasetError(f"в эталоне есть вопросы, которых нет в наборе: {', '.join(unknown[:5])}")
    (root / "answers_public.json").write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"gold": len(gids), "questions": len(qids), "missing": sorted(qids - gids)}


def from_files(files: list[tuple[str, bytes]], name: str, package: str = "P01") -> str:
    """Загрузка отдельных .txt — одна закупка, вопросы будут строкой ввода."""
    if not package or PurePosixPath(package).name != package or package in (".", "..") or "\\" in package:
        raise DatasetError("имя закупки должно быть именем одной папки")
    did, dest = _new_dir(name)
    try:
        for fname, data in files:
            if fname.lower().endswith(".txt"):
                basename = PurePosixPath(fname.replace("\\", "/")).name
                _write(dest / "packages" / package / basename, data)
            elif std := standard_name(PurePosixPath(fname.replace("\\", "/")).name):
                _write(dest / std, data)
        if not (dest / "packages").exists():
            raise DatasetError("нужен хотя бы один .txt")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return did


def _write(path: Path, data: bytes) -> None:
    if any(ord(c) < 32 for c in path.name):
        raise DatasetError("недопустимый управляющий символ в имени файла")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError as exc:
        raise DatasetError(f"повторяющееся имя файла в закупке: {path.name}") from exc


def subset(dataset_id: str, ids: list[str], name: str) -> str:
    """Поднабор вопросов (с их эталоном и только нужными закупками) — чтобы гонять дорогие
    эксперименты, например на медленной локальной модели, только на показательных вопросах."""
    import csv
    src = path_of(dataset_id)
    want = set(ids)
    did, dest = _new_dir(name)
    with open(src / "questions.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f, delimiter=";") if r["id"] in want]
    available = set(info(dataset_id)["packages"])
    if any(row["package"] not in available for row in rows):
        shutil.rmtree(dest)
        raise DatasetError("неизвестная закупка в questions.csv")
    if not rows:
        shutil.rmtree(dest)
        raise DatasetError("ни одного вопроса из списка нет в датасете")
    with open(dest / "questions.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "package", "question"], delimiter=";")
        w.writeheader()
        w.writerows({k: r[k] for k in ("id", "package", "question")} for r in rows)
    if (src / "answers_public.json").exists():
        gold = [g for g in json.loads((src / "answers_public.json").read_text(encoding="utf-8")) if g["id"] in want]
        (dest / "answers_public.json").write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")
    for pkg in sorted({r["package"] for r in rows}):
        shutil.copytree(src / "packages" / pkg, dest / "packages" / pkg)
    return did
