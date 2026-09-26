# TopicEye on Oracle ARM64 (`textura.top`)

This deployment is for the existing **Oracle 2-vCPU ARM64 / ~12 GB RAM**
server. It runs **only TopicEye frontend and backend**. It deliberately
reuses existing `textura-postgres` (PostgreSQL 18), `textura-gptload` (V2),
`textura-rsshub`, `textura-npm`, and `textura-cloudflared`; it does not
create duplicate PostgreSQL, Nginx, Certbot, or Ollama services.

**Verification status:** configuration and repository wiring have been reviewed,
but ARM64 image builds, running services, and reachability on your Oracle host
still require on-server verification.

## Architecture

```text
Public HTTPS -> Cloudflare Tunnel -> NPM -> topiceye-frontend:3000
                                             | Next.js /api rewrites
                                             v
                                       topiceye-backend:8000
                                           |         |
                                 textura-db-net   textura-net
                                           |         |
                                     postgres:5432  gptload:3001 / rsshub:1200
```

The Compose file creates a private `app-net` between frontend/backend. The
frontend alone is published to the existing `textura-net` **Docker network**
so NPM can reach it; backend also joins `textura-net` for GPT-Load/RSSHub and
`textura-db-net` for PostgreSQL. **Neither publishes a host port.** No changes
to your current SSH-only Navicat access or PostgreSQL backup setup are needed.

## 1. Check existing infrastructure

On the Oracle server:

```bash
docker network ls
docker network inspect textura-net --format '{{range .Containers}}{{println .Name}}{{end}}'
docker network inspect textura-db-net --format '{{range .Containers}}{{println .Name}}{{end}}'
docker ps --format 'table {{.Names}}\t{{.Status}}'
```

Check `textura-postgres`, `textura-gptload`, `textura-npm`, and
`textura-cloudflared` are running. Your existing Compose definitions should
give the PG container the network alias `postgres` on `textura-db-net`, and
GPT-Load the alias `gptload` on `textura-net`. Do not expose the database's
port 5432 to the public Internet.

Clone or update the repository on the server:

```bash
sudo mkdir -p /opt/textura
sudo chown "$USER:$(id -gn)" /opt/textura
git clone https://github.com/fxbin/TopicEye.git /opt/textura/topiceye
cd /opt/textura/topiceye
```

If testing this PR before merging, check out `feat/oracle-textura-deployment`
first. If a checkout already exists, update it rather than re-cloning.

## 2. Create TopicEye's own database and role

Do not reuse the `postgres` superuser or overwrite the existing `textura`
database. Use the existing PG18 container:

```bash
docker exec -it textura-postgres psql -U postgres -d textura
```

Inside `psql`:

```sql
CREATE ROLE topiceye LOGIN;
\password topiceye
CREATE DATABASE topiceye OWNER topiceye;
\q
```

Enter the database password interactively; do not paste it into SQL committed
to Git. If this database/role already exists, inspect it before running the
creation commands. PostgreSQL 18 and the bundled DuckDB `postgres` extension
must be verified together on ARM64; the repo's earlier default used PG16.

Your existing instance-level `pg_dumpall` Cron backup should include this new
database and role. Keep an off-host backup and test recovery.

## 3. Create local environment, never commit credentials

```bash
cd /opt/textura/topiceye
cp deploy/oracle/env.example .env
chmod 600 .env
openssl rand -hex 32   # APP_SECRET_KEY: store privately
openssl rand -hex 32   # INTEGRATION_SECRET_KEY: different, store privately
nano .env
```

Replace *all* `CHANGE_ME` values. Keep the PostgreSQL hostname `postgres`
(port 5432) because it is a Docker-network alias, not the Oracle public IP.
URL-encode the database password before placing it in `DATABASE_URL`:

```bash
python3 -c 'from urllib.parse import quote; import getpass; print(quote(getpass.getpass("Database password: "), safe=""))'
```

For example, characters like `@`, `#`, `%` and `:` require encoding. Compose
also interpolates `$` in env files, so handle that correctly or use a strong
generated password without that character. Never commit the populated `.env`.

Use a new `APP_SECRET_KEY` and `INTEGRATION_SECRET_KEY` on the first start:
losing/changing the latter may prevent decryption of saved integration keys.
If you need admin bootstrap, temporarily set
`ADMIN_SEED_ENABLED=true`, `ADMIN_EMAIL`, and a **strong unique**
`ADMIN_PASSWORD`. Disable seeding once the admin login is verified.

The template sets `AUTH_COOKIE_SECURE=true` for HTTPS, conservative
`SOURCE_SYNC_WORKER_CONCURRENCY=1`, `TRENDING_SYNC_CONCURRENCY=2`,
`DB_POOL_SIZE=5` and `DUCKDB_THREADS=1`. The backend's pre-downloaded DuckDB
extension is copied to `/opt/duckdb_extensions` at build time, outside the
`/app/data` persistent-volume mount. ARM64 availability/build success still
needs real testing; `DUCKDB_STARTUP_INIT_ENABLED=false` avoids holding up
initial API startup and allows the existing SQLAlchemy fallback.

## 4. Preflight, build and smoke test

```bash
cd /opt/textura/topiceye
bash deploy/oracle/verify.sh preflight
docker compose -f docker-compose.oracle.yml build
docker compose -f docker-compose.oracle.yml up -d
docker compose -f docker-compose.oracle.yml ps
docker compose -f docker-compose.oracle.yml logs --tail=100 backend frontend
bash deploy/oracle/verify.sh smoke
```

If the first ARM64 image build fails at native packages or DuckDB extension
installation, stop and inspect its logs; do **not** assume a successful
Debian/AMD64 build guarantees an ARM64 build. For database errors, check the
role/database, URL-encoded password, network aliases and PostgreSQL logs.
Do not loosen `pg_hba.conf` to admit the whole Internet.

Resource limits start at **1.5 GiB / 1 CPU** for backend and
**768 MiB / 0.75 CPU** for frontend. Monitor `docker stats` and `free -h`.
Ollama's 2-core saturated CPU inference will contend with TopicEye scraping;
avoid large local inference alongside bulk syncing.

## 5. Publish through existing NPM + Cloudflare Tunnel

Only *after* internal smoke tests pass:

1. NPM → Proxy Hosts → Add: domain `topic.textura.top`, Scheme `http`,
   Forward hostname **`topiceye-frontend`**, port **`3000`**. Avoid
   directly publishing `topiceye-backend:8000`.
2. Existing Cloudflare Tunnel → Published application route:
   `topic.textura.top` → **`http://npm:80`**.
3. Cloudflare handles the public HTTPS connection. Keep
   `CORS_ORIGINS=https://topic.textura.top`, `AUTH_COOKIE_SECURE=true`
   and `SITE_BASE_URL=https://topic.textura.top`.

Validate `https://topic.textura.top/health/live` and normal login. If enabling
Google/GitHub OAuth, register the callback
`https://topic.textura.top/api/v1/auth/oauth/{google,github}/callback`
for the chosen provider; the frontend callback is
`https://topic.textura.top/oauth/callback`.

**Authentication note:** TopicEye uses its own sessions and Bearer API tokens.
Putting NPM Basic Auth over the *entire* app can conflict with Authorization
headers and OAuth redirects. Configure TopicEye login, confirm registration
policy, and optionally IP-restrict a private preview instead. Review access
to operational routes before public launch.

## 6. Reuse GPT-Load and RSSHub **internally**

TopicEye's current LLM management UI stores providers/models/routes in its
database and uses LiteLLM; **do not invent a `GPTLOAD_URL` environment
variable**. In the admin AI model settings, use its OpenAI-compatible preset:

| Setting | Value |
| --- | --- |
| Provider | OpenAI compatible (`openai`) |
| API Base | `http://gptload:3001/v1` |
| Model ID | The actual GPT-Load V2 model/group identifier |
| API Key | A dedicated **client AccessKey**, not the GPT-Load admin key |
| Routing group | Start with `default` |

Verify a real short completion before enabling scheduled AI jobs. TopicEye
and GPT-Load *both* have retries/failover: configure one stable route first,
then tune one orchestration layer deliberately. TopicEye has a **45-second
default hard completion timeout**. Your MiniCPM5-2B long-input benchmark
took about **17 minutes** on this CPU, so don't route normal analyses to the
local Ollama model or globally raise all completion timeouts. Use cloud models
through GPT-Load for the primary analysis path.

For server-side TopicEye feed URLs, RSSHub can be referenced internally as
`http://rsshub:1200/<route>` instead of using the NPM Basic Auth protected
public RSSHub domain. Container-only names are not browser-facing URLs.

## 7. Operate, back up and update

```bash
docker stats --no-stream
free -h
docker compose -f docker-compose.oracle.yml logs -f --tail=80
```

Verify your normal PG backup before upgrades and periodically test restoration.
Schema migrations run at startup by default, so a backup is especially
important before changes to backend models/migrations. To restart only TopicEye:

```bash
cd /opt/textura/topiceye
docker compose -f docker-compose.oracle.yml stop
# Update to a reviewed commit, confirm backup, then:
docker compose -f docker-compose.oracle.yml build
docker compose -f docker-compose.oracle.yml up -d
```

Do not run `docker compose down -v` in production; it deletes TopicEye's
persistent data volume. This Oracle compose does **not** manage the shared
PostgreSQL/NPM/GPT-Load services. Don't run the generic
`deploy/deploy.sh` for this host, because it manages an additional
Nginx/Certbot deployment.
