FROM python:3.12-slim

WORKDIR /app

# 1) 先单独装 duckdb 并触发 postgres 扩展下载到 /root/.duckdb/extensions
#    国内服务器从 extensions.duckdb.org 拉扩展经常被 GFW 阻断或极慢，
#    在 build 阶段就把它预下载好。requirements.txt 里再装 duckdb 时是 no-op。
#    后续运行时 INSTALL postgres; LOAD postgres; 不会再下载（除非被清空）。
ARG DUCKDB_VERSION=1.2.2
RUN pip install --no-cache-dir "duckdb==${DUCKDB_VERSION}" && \
    python -c "import duckdb; con=duckdb.connect(':memory:'); con.execute('INSTALL postgres; LOAD postgres;')" && \
    rm -rf /root/.cache/pip

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=5 \
    PIP_INDEX_URL=${PIP_INDEX_URL}

# 2) 装剩余依赖（duckdb 已就位，pip 会跳过）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /root/.cache/pip

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live').read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]
