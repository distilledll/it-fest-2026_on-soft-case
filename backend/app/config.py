from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # корень монорепы


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Встроенный пример организатора (датасет "sample") и оценщик по умолчанию.
    sample_dir: Path = ROOT / "data" / "sample"
    checker: Path = ROOT / "data" / "sample" / "check.py"
    # Всё, что меняется в рантайме: загруженные датасеты, прогоны, models.json.
    storage_dir: Path = ROOT / "storage"

    pipeline: str = "baseline"

    # Профиль модели по умолчанию (создаётся при первом запуске, если models.json пуст).
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key_env: str = "LLM_API_KEY"   # имя переменной с ключом, сам ключ — в .env
    llm_extra_headers: str = ""            # "User-Agent=Mozilla/5.0 ...;X-Foo=bar"

    max_concurrency: int = 4
    question_timeout_s: float = 180.0
    max_upload_mb: int = 200

    @property
    def datasets_dir(self) -> Path:
        return self.storage_dir / "datasets"

    @property
    def runs_dir(self) -> Path:
        return self.storage_dir / "runs"


settings = Settings()
