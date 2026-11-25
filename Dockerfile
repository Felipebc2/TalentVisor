FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

# STT model: early layer, independent of pyproject/uv.lock. Repo = what faster-whisper maps STT_MODEL to.
ARG STT_MODEL=large-v3-turbo
ARG STT_REPO=mobiuslabsgmbh/faster-whisper-large-v3-turbo
ENV HF_HUB_CACHE=/models STT_MODEL=${STT_MODEL}
RUN uv pip install --system --break-system-packages huggingface_hub \
    && python -c "from huggingface_hub import snapshot_download; snapshot_download('${STT_REPO}')"
ENV HF_HUB_OFFLINE=1

# Deps (incl. dev group) + spaCy pt_core_news_md (a locked dependency) into /opt/venv. Code comes via bind mount.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health', timeout=4)"
CMD ["uvicorn", "talentvisor.app:app", "--host", "0.0.0.0", "--port", "8000"]
