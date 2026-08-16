# TopicEye Backend

FastAPI + SQLAlchemy + PostgreSQL backend for TopicEye.

## Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
./venv/bin/python -m uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

## Database backend

The backend runtime requires PostgreSQL through `DATABASE_URL` (the startup
validator rejects anything else; SQLite support has been removed):

- PostgreSQL: `postgresql+asyncpg://user:password@host:5432/topiceye`

SQLAlchemy remains the write path. DuckDB is the analytical read layer and
attaches the configured OLTP database in read-only mode. Backend-specific URL
normalization, DuckDB attach SQL, diagnostics, and secret redaction live in
`app/core/db_backend.py`.

Important boundaries:

- Schema upgrades run through Alembic on startup (`run_startup_migrations`
  stamps legacy databases and upgrades to head).
- `backup_db.sh` / `rollback_migration.sh` operate on PostgreSQL only.

## Tests

```bash
# 从仓库根目录：自动起一次性 PG 容器（127.0.0.1:5433），跑完即删
make test-backend

# 或直接调用脚本（可透传 pytest 参数）
bash backend/scripts/test_full_local.sh
```

Files such as `scripts/duckdb_check.py`, `scripts/estimate_llm_cost.py`,
`scripts/duckdb_perf.py`, and `scripts/perf_baseline.py` are manual diagnostics
rather than pytest tests.

## Manual diagnostics

```bash
cd backend
python scripts/duckdb_perf.py
python scripts/perf_baseline.py
python scripts/duckdb_check.py
```

Operational helper scripts live under `scripts/` as well. For example,
`scripts/batch_analyze.sh` analyzes pending content through the HTTP API and
works against any running backend:

```bash
cd backend
AUTH_TOKEN=<login-token> BASE_URL=http://localhost:8000 ./scripts/batch_analyze.sh
```
