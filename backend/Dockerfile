# ── Stage 1: Builder ──────────────────────────────────────────────
# Install dependencies with uv from the committed uv.lock, compile native
# extensions if needed, pre-download DuckDB extensions. These artifacts are
# copied to the runtime stage; gcc / g++ / headers stay here and are discarded.
FROM python:3.12-slim AS builder

WORKDIR /app

# Build tools for packages that may need compilation
# (mini-racer → V8 C++ bindings, lxml/trafilatura, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# uv：与本地 uv sync 同源的锁定安装（版本与开发机对齐）
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/

# 镜像源在 pyproject.toml [tool.uv.index] 里提交（清华 TUNA），构建无需额外参数
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=60

# 先只拷依赖清单，充分利用 layer 缓存；代码变更不会触发依赖重装
COPY pyproject.toml uv.lock ./
# --frozen 只按 uv.lock 安装不重新解析；--no-dev 不装测试/lint 工具
# （uv 建的 venv 不含 pip/setuptools，无需原来的卸载瘦身步骤）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev && \
    find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
    find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; \
    rm -rf /opt/venv/lib/python3.12/site-packages/*.dist-info/*.egg-info

# DuckDB 预下载需要 venv 里的 duckdb 包
ENV PATH="/opt/venv/bin:$PATH"

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
