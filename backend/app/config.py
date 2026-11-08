from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # корень монорепы
BACKEND = ROOT / "backend"

# Ключи моделей ищутся по имени переменной (api_key_env) в окружении — поэтому .env грузим в os.environ.
# Уже заданные переменные окружения (docker env_file, CI) не перетираем.
load_dotenv(BACKEND / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND / ".env", extra="ignore")

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

    max_concurrency: int = 2        # сколько вопросов прогона обрабатываются одновременно
    llm_concurrency: int = 1        # сколько запросов к API одновременно (лимит шлюза на организацию)
    llm_retries: int = 8            # повторы на 429/5xx/сетевых ошибках
    llm_timeout_s: float = 90.0     # таймаут одного запроса к API
    question_timeout_s: float = 600.0   # на весь вопрос, включая ожидание очереди и повторы
    max_upload_mb: int = 200
    embed_dimensions: int = 256     # размерность эмбеддингов для поиска фрагментов (меньше — быстрее и легче кэш)

    @property
    def datasets_dir(self) -> Path:
        return self.storage_dir / "datasets"

    @property
    def runs_dir(self) -> Path:
        return self.storage_dir / "runs"


settings = Settings()
