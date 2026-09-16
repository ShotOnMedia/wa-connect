#!/usr/bin/env bash
set -Eeuo pipefail

BACKUP_DIR="${1:?Usage: restore.sh /path/to/backup --confirm}"
CONFIRM="${2:-}"
[[ "$CONFIRM" == "--confirm" ]] || { echo "Restore is destructive. Re-run with --confirm." >&2; exit 2; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
COMPOSE_FILE="${BACKUP_COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${BACKUP_ENV_FILE:-.env}"

"$ROOT_DIR/deploy/backup/verify.sh" "$BACKUP_DIR"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
DB_NAME="${MARIADB_DATABASE:-wa_connect}"
DB_USER="${MARIADB_USER:-wa_connect}"
DB_PASS="${MARIADB_PASSWORD:?MARIADB_PASSWORD is required}"
MEDIA_PATH="${MEDIA_LOCAL_HOST_PATH:-./storage/inbound-media}"
[[ "$MEDIA_PATH" = /* ]] || MEDIA_PATH="$ROOT_DIR/${MEDIA_PATH#./}"

printf 'This will REPLACE database "%s" and media at "%s". Type RESTORE: ' "$DB_NAME" "$MEDIA_PATH"
read -r answer
[[ "$answer" == "RESTORE" ]] || { echo "Restore cancelled."; exit 2; }

echo "Stopping API and worker to prevent writes..."
docker compose -f "$COMPOSE_FILE" stop api delay-worker
trap 'docker compose -f "$COMPOSE_FILE" start api delay-worker >/dev/null 2>&1 || true' EXIT

echo "Recreating database..."
docker compose -f "$COMPOSE_FILE" exec -T -e MYSQL_PWD="$MARIADB_ROOT_PASSWORD" db mariadb -uroot <<SQL
DROP DATABASE IF EXISTS \`$DB_NAME\`;
CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'%';
FLUSH PRIVILEGES;
SQL

echo "Restoring database..."
gzip -dc "$BACKUP_DIR/database.sql.gz" | docker compose -f "$COMPOSE_FILE" exec -T -e MYSQL_PWD="$DB_PASS" db mariadb -u"$DB_USER" "$DB_NAME"

echo "Restoring media..."
mkdir -p "$MEDIA_PATH"
find "$MEDIA_PATH" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
tar -C "$MEDIA_PATH" -xzf "$BACKUP_DIR/media.tar.gz"

echo "Starting services..."
docker compose -f "$COMPOSE_FILE" start api delay-worker
trap - EXIT

echo "Restore completed. Verify /health and application data before reopening traffic."
echo "production.env(.enc) is intentionally NOT restored automatically; compare it manually."
