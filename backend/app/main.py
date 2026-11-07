from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import llm
from app.api import ask, datasets, models, runs
from app.config import settings
from app.pipeline.base import available

settings.runs_dir.mkdir(parents=True, exist_ok=True)
settings.datasets_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ОНСОФТ: ИИ, который не обманывает")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (datasets.router, models.router, ask.router, runs.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    reg = llm.load()
    return {"ok": True, "default_pipeline": settings.pipeline, "pipelines": available(),
            "roles": {r: next((p.model for p in reg.profiles if p.id == pid), None) for r, pid in reg.roles.items()}}
