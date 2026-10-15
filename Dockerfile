# syntax=docker/dockerfile:1
FROM python:3.13-slim

# WITH_TRAINING=true adds PyTorch/Transformers for the offline model (large; needs an NVIDIA GPU host).
ARG WITH_TRAINING=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RUSHD_DATA_DIR=/data \
    RUSHD_SECRETS_DIR=/secrets \
    RUSHD_FRONTEND_DIR=/app/frontend \
    HF_HOME=/data/hf-cache

RUN groupadd --system --gid 10001 rushd \
 && useradd --system --uid 10001 --gid rushd --home-dir /app --shell /usr/sbin/nologin rushd

WORKDIR /app/backend
COPY backend/requirements.txt backend/requirements-train.txt ./
RUN pip install -r requirements.txt \
 && if [ "$WITH_TRAINING" = "true" ]; then pip install -r requirements-train.txt; fi

COPY backend/rushd ./rushd
COPY frontend /app/frontend
COPY deploy/entrypoint.sh /usr/local/bin/rushd-entrypoint

RUN mkdir -p /data /secrets \
 && chown rushd:rushd /data /secrets \
 && chmod 700 /data /secrets

USER rushd
EXPOSE 8000
VOLUME ["/data", "/secrets"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
ENTRYPOINT ["rushd-entrypoint"]
