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
