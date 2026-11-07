import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path, monkeypatch):
    """Каждый тест — с чистым storage, реальные прогоны и models.json не трогаем."""
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "llm_base_url", "")
    settings.runs_dir.mkdir(parents=True)
    settings.datasets_dir.mkdir(parents=True)
    yield
