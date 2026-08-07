# ── Stage 1: Builder ──────────────────────────────────────────────
# Install dependencies with build tools, compile native extensions,
# pre-download DuckDB extensions. These artifacts are copied to the
# runtime stage; gcc / g++ / headers stay here and are discarded.
FROM python:3.12-slim AS builder

WORKDIR /app

# Build tools for packages that may need compilation
# (mini-racer → V8 C++ bindings, lxml/trafilatura, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=5 \
    PIP_INDEX_URL=${PIP_INDEX_URL}

# Use a virtualenv so we can copy the entire install as one unit
# into the runtime stage without touching system site-packages.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/pip && \
    # Strip build-only tools and caches from venv to shrink runtime image
    pip uninstall -y pip setuptools wheel && \
    find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
    rm -rf /opt/venv/lib/python3.12/site-packages/*.dist-info/*.egg-info

# Pre-download DuckDB postgres extension to the runtime path.
# 国内服务器从 extensions.duckdb.org 拉扩展经常被 GFW 阻断或极慢，
# 在 build 阶段预下载到 DUCKDB_EXTENSION_DIR，运行时 INSTALL 是 no-op。
ARG DUCKDB_EXTENSION_DIR=/app/data/duckdb_extensions
RUN mkdir -p ${DUCKDB_EXTENSION_DIR} && \
    python -c "import duckdb; con=duckdb.connect(':memory:'); con.execute(\"SET extension_directory='${DUCKDB_EXTENSION_DIR}'\"); con.execute('INSTALL postgres; LOAD postgres;')"

# ── Stage 2: Runtime ──────────────────────────────────────────────
# Slim image: no gcc, no dev headers, no pip cache.
# Only the venv, DuckDB extensions, and application code.
FROM python:3.12-slim

WORKDIR /app

# Copy venv (all installed packages + console scripts like uvicorn)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy pre-downloaded DuckDB extensions to the path the app expects
COPY --from=builder /app/data/duckdb_extensions /app/data/duckdb_extensions

# Copy application code
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live').read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]
