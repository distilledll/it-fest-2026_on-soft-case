"""Датасеты: загрузка zip / отдельных .txt, просмотр закупок и документов."""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import datasets
from app.api import out
from app.config import settings
from app.datasets import DatasetError
from app.ingest import load_package, load_questions
from app.schemas import Document, Question

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _dir(did: str):
    try:
        return datasets.path_of(did)
    except DatasetError as e:
        raise HTTPException(404, str(e))


@router.get("", response_model=list[out.DatasetInfo])
def list_datasets():
    return datasets.list_all()


@router.post("", status_code=201, response_model=out.DatasetInfo)
async def upload(files: list[UploadFile] = File(...), name: str = Form(""), package: str = Form("P01")):
    """Один .zip (формат организатора или любая структура с .txt) или несколько .txt одной закупки."""
    limit = settings.max_upload_mb * 2**20
    blobs = []
    for f in files:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"{f.filename}: больше {settings.max_upload_mb} МБ")
        blobs.append((f.filename or "file", data))
    try:
        if len(blobs) == 1 and blobs[0][0].lower().endswith(".zip"):
            did = datasets.from_zip(blobs[0][1], name or blobs[0][0])
        else:
            did = datasets.from_files(blobs, name or "Загруженные файлы", package)
    except DatasetError as e:
        raise HTTPException(422, str(e))
    return datasets.info(did)


@router.get("/{did}", response_model=out.DatasetDetail)
def get_dataset(did: str):
    root = _dir(did)
    return {**datasets.info(did),
            "files": {p: [d.model_dump(exclude={"text"}) for d in load_package(root, p)]
                      for p in datasets.info(did)["packages"]}}


@router.delete("/{did}", status_code=204)
def delete_dataset(did: str):
    try:
        datasets.delete(did)
    except DatasetError as e:
        raise HTTPException(400, str(e))


@router.get("/{did}/questions", response_model=list[Question])
def questions(did: str):
    root = _dir(did)
    return load_questions(root) if (root / "questions.csv").exists() else []


@router.get("/{did}/packages/{package}/files/{file}", response_model=Document)
def document(did: str, package: str, file: str):
    """Полный текст документа — для подсветки цитаты на фронте."""
    for d in load_package(_dir(did), package):
        if d.file == file:
            return d
    raise HTTPException(404)
