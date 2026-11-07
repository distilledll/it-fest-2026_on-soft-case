# Сборка из корня репозитория: docker compose build
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /repo/backend
COPY backend/pyproject.toml ./
COPY backend/app/ app/
RUN pip install ".[agent]"
ENV STORAGE_DIR=/repo/storage
RUN useradd -m appuser && mkdir -p /repo/storage && chown -R appuser /repo/storage
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
