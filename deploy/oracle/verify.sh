#!/usr/bin/env bash
# Usage: bash deploy/oracle/verify.sh [preflight|smoke]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:-preflight}"

command -v docker >/dev/null || { echo 'Docker is not installed.' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Docker daemon is unavailable.' >&2; exit 1; }

for net in textura-net textura-db-net; do
  docker network inspect "$net" >/dev/null 2>&1 || { echo "Missing network: $net" >&2; exit 1; }
done
for container in textura-postgres textura-gptload textura-npm textura-cloudflared; do
  status="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
  [[ "$status" == running ]] || { echo "Required container not running: $container ($status)" >&2; exit 1; }
done

[[ -f "$ROOT/.env" ]] || { echo 'Create .env from deploy/oracle/env.example first.' >&2; exit 1; }
if grep -Eq '^((DATABASE_URL|APP_SECRET_KEY|INTEGRATION_SECRET_KEY)=.*CHANGE_ME)' "$ROOT/.env"; then
  echo 'Replace CHANGE_ME values in .env before deploying.' >&2
  exit 1
fi

(cd "$ROOT" && docker compose -f docker-compose.oracle.yml config --quiet)
echo 'Compose syntax, external networks, and dependent containers: OK.'

case "$MODE" in
  preflight) ;;
  smoke)
    docker inspect -f '{{.State.Health.Status}}' topiceye-backend | grep -qx healthy
    docker inspect -f '{{.State.Health.Status}}' topiceye-frontend | grep -qx healthy
    docker run --rm --network textura-net curlimages/curl:latest \
      --fail --silent --show-error --max-time 15 \
      http://topiceye-frontend:3000/health/live >/dev/null
    echo 'Frontend -> backend rewrite and both health checks: OK.'
    ;;
  *) echo "Unknown mode: $MODE (preflight or smoke)" >&2; exit 2 ;;
esac
