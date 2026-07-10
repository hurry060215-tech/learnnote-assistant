FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LEARNNOTE_DATA_DIR=/app/data \
    LEARNNOTE_DEPLOYMENT_MODE=server \
    HF_HOME=/app/data/model-cache/huggingface \
    XDG_CACHE_HOME=/app/data/model-cache/xdg \
    TORCH_HOME=/app/data/model-cache/torch \
    TMP=/app/data/temp \
    TEMP=/app/data/temp \
    TMPDIR=/app/data/temp

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 learnnote

WORKDIR /app
COPY backend/requirements.txt backend/requirements.deploy.txt /app/backend/
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/backend/requirements.deploy.txt

COPY backend /app/backend
COPY web /app/web
RUN mkdir -p /app/data \
    && chown -R learnnote:learnnote /app

USER learnnote
WORKDIR /app/backend
VOLUME ["/app/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3))['ok']" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8765} --proxy-headers --forwarded-allow-ips='*'"]
