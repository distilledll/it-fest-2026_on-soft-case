import pytest

from app.config import settings

HAS_SAMPLE = (settings.sample_dir / "packages").is_dir()
needs_sample = pytest.mark.skipif(not HAS_SAMPLE, reason="нет data/sample (данные организатора не в репо)")


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path, monkeypatch):
    """Каждый тест — с чистым storage, реальные прогоны и models.json не трогаем."""
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "llm_base_url", "")
    settings.runs_dir.mkdir(parents=True)
    settings.datasets_dir.mkdir(parents=True)
    yield
