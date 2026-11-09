import io
import zipfile

import pytest

from app import datasets
from app.datasets import DatasetError


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_organizer_layout_nested():
    did = datasets.from_zip(make_zip({
        "set/packages/P01/01.txt": "текст".encode(),
        "set/questions.csv": b"id;package;question\nP01-01;P01;q\n",
        "set/README.md": b"skip",
    }), "x")
    info = datasets.info(did)
    assert info["packages"] == ["P01"] and info["has_questions"] and not info["has_gold"]


def test_loose_txt_without_questions():
    did = datasets.from_zip(make_zip({"a.txt": b"1", "lot2/b.txt": b"2"}), "x")
    assert datasets.info(did)["packages"] == ["P01", "lot2"]
    assert not datasets.info(did)["has_questions"]


def test_zip_slip_is_ignored():
    with pytest.raises(DatasetError):
        datasets.from_zip(make_zip({"../../evil.txt": b"x", "/abs.txt": b"y"}), "x")


def test_not_zip():
    with pytest.raises(DatasetError):
        datasets.from_zip(b"not a zip", "x")


def test_bad_id():
    with pytest.raises(DatasetError):
        datasets.path_of("../etc")


def test_from_files():
    did = datasets.from_files([("doc.txt", "привет".encode("cp1251")), ("evil.exe", b"x")], "x", "P09")
    assert datasets.info(did)["packages"] == ["P09"]


def test_subset_keeps_gold_and_packages():
    import json
    did = datasets.from_zip(make_zip({
        "packages/P01/a.txt": "текст".encode(), "packages/P02/b.txt": "текст".encode(),
        "questions.csv": "id;package;question\nP01-01;P01;q1\nP02-01;P02;q2\n".encode(),
        "answers_public.json": json.dumps([{"id": "P01-01"}, {"id": "P02-01"}]).encode(),
    }), "x")
    sub = datasets.subset(did, ["P02-01"], "s")
    info = datasets.info(sub)
    assert info["packages"] == ["P02"] and info["has_gold"]
    assert [g["id"] for g in json.loads((datasets.path_of(sub) / "answers_public.json").read_text())] == ["P02-01"]


def test_checker_from_archive_or_repo():
    from app.config import settings
    own = datasets.from_zip(make_zip({"packages/P01/a.txt": "т".encode(), "check.py": b"print('RESULT {}')"}), "x")
    path, src = datasets.checker_for(datasets.path_of(own))
    assert not (datasets.path_of(own) / "check.py").exists()
    assert path == settings.checker and "эталонный" in src
    plain = datasets.from_zip(make_zip({"packages/P01/a.txt": "т".encode()}), "y")
    path, src = datasets.checker_for(datasets.path_of(plain))
    assert path == settings.checker and path.is_file() and "эталонный" in datasets.info(plain)["checker"]


@pytest.mark.parametrize("archive", [True, False])
@pytest.mark.parametrize("reverse", [True, False])
def test_import_preserves_distinct_source_names(archive, reverse):
    from app.ingest import load_package

    files = [("Приложение 1.txt", b"14"), ("Приложение_1.txt", b"26")]
    if reverse:
        files.reverse()
    if archive:
        did = datasets.from_zip(make_zip({f"packages/P/{f}": data for f, data in files}), "audit")
    else:
        did = datasets.from_files(files, "audit", "P")
    docs = load_package(datasets.path_of(did), "P")
    assert {d.file: d.text for d in docs} == {f: data.decode() for f, data in files}


def test_duplicate_upload_is_rejected_and_rolled_back():
    from app.config import settings

    with pytest.raises(DatasetError, match="a.txt"):
        datasets.from_files([("a.txt", b"14"), ("a.txt", b"26")], "duplicate")
    assert not list(settings.datasets_dir.iterdir())
