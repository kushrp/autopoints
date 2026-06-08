# syntax=docker/dockerfile:1
# Multi-stage build for a slim runtime image.
# Builder stage installs Python deps with build tools available; runtime
# stage copies only the installed packages + source code.

FROM python:3.11-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build

# git is required because pyproject.toml declares `flights @ git+https://github.com/punitarani/fli.git@main`
# (PEP 508 direct URL). The PyPI `flights` namespace points at an unrelated
# package, so we install fli from its GitHub source — pip needs git to clone.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY autopoints autopoints
RUN pip install --target=/install ".[discord]"


FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/deps \
    PATH=/app/deps/bin:$PATH \
    AUTOPOINTS_CACHE_PATH=/data/cache.db \
    AUTOPOINTS_HOST=0.0.0.0 \
    AUTOPOINTS_PORT=8000

RUN useradd --create-home --uid 1000 app \
 && mkdir -p /data \
 && chown -R app:app /data

WORKDIR /app
COPY --from=builder /install /app/deps
COPY autopoints autopoints
RUN chown -R app:app /app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "autopoints.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
