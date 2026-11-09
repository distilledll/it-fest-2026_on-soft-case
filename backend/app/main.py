from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import llm
from app.api import ask, datasets, models, out, runs
from app.config import ROOT, settings
from app.pipeline.base import available

settings.runs_dir.mkdir(parents=True, exist_ok=True)
settings.datasets_dir.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await llm.close_clients()


app = FastAPI(
    lifespan=lifespan,
    title="ОНСОФТ: ИИ, который не обманывает",
    version="0.4.0",
    description=(
        "Бэкенд ИИ-помощника по документам госзакупок: ответы с дословной цитатой, проверки кодом и моделью, "
        "честное «не знаю».\n\n"
        "Сценарии для фронта — в `backend/docs/frontend.md`. Без модели можно работать с `\"pipeline\": \"stub\"`."),
    openapi_tags=[
        {"name": "health", "description": "Состояние бэка: пайплайны, модели по ролям"},
        {"name": "datasets", "description": "Датасеты: пример организатора и загруженные zip / .txt"},
        {"name": "models", "description": "Профили моделей (OpenAI-совместимый API) и роли"},
        {"name": "ask", "description": "Вопрос строкой ввода — в том числе живой вопрос жюри (SSE)"},
        {"name": "runs", "description": "Прогоны набора вопросов, оценка check.py, пойманные обманы, сравнение"},
        {"name": "ladders", "description": "Лесенка «было → стало»: baseline → промпт → критики → критик-модель"},
    ],
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (datasets.router, models.router, ask.router, runs.router, runs.ladders_router):
    app.include_router(r)


@app.get("/api/health", response_model=out.HealthOut, tags=["health"])
def health():
    reg = llm.load()
    return {"ok": True, "default_pipeline": settings.pipeline, "pipelines": available(),
            "roles": {r: next((p.model for p in reg.profiles if p.id == pid), None) for r, pid in reg.roles.items()}}


# В production Vue и API обслуживаются с одного адреса.
web_dir = ROOT / "frontend" / "dist"
if (web_dir / "index.html").is_file():
    @app.get("/login", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    @app.get("/upload", include_in_schema=False)
    @app.get("/settings", include_in_schema=False)
    def frontend_page():
        return FileResponse(web_dir / "index.html")

    app.mount("/", StaticFiles(directory=web_dir, html=True), name="frontend")
