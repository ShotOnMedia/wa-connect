#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

BACKUP_DIR="${1:?Usage: restore.sh /path/to/backup --confirm}"
CONFIRM="${2:-}"
[[ "$CONFIRM" == "--confirm" ]] || { echo "Restore is destructive. Re-run with --confirm." >&2; exit 2; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
COMPOSE_FILE="${BACKUP_COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${BACKUP_ENV_FILE:-.env}"

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }
[[ -f "$COMPOSE_FILE" ]] || { echo "Missing $COMPOSE_FILE" >&2; exit 1; }
[[ -d "$BACKUP_DIR" ]] || { echo "Backup directory not found: $BACKUP_DIR" >&2; exit 1; }
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"

"$ROOT_DIR/deploy/backup/verify.sh" "$BACKUP_DIR"

# Read resolved database credentials from the running db container instead of
# sourcing the Docker Compose .env file as shell code.
DB_CONTAINER="$(docker compose -f "$COMPOSE_FILE" ps -q db)"
[[ -n "$DB_CONTAINER" ]] || { echo "Database container is not running for $COMPOSE_FILE" >&2; exit 1; }

container_env() {
  local key="$1"
  docker inspect "$DB_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | sed -n "s/^${key}=//p" | head -n1
}

env_value() {
  local key="$1" line value
  line="$(grep -m1 -E "^[[:space:]]*${key}=" "$ENV_FILE" || true)"
  [[ -n "$line" ]] || return 1
  value="${line#*=}"
  value="${value%$'\r'}"
  if [[ ${#value} -ge 2 ]]; then
    if [[ "${value:0:1}" == '"' && "${value: -1}" == '"' ]] || [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1:${#value}-2}"
    fi
  fi
  printf '%s' "$value"
}

manifest_value() {
  local key="$1"
  python3 - "$BACKUP_DIR/manifest.json" "$key" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
value = data.get(sys.argv[2], "")
print(value if value is not None else "")
PY
}

DB_NAME="$(container_env MARIADB_DATABASE)"
DB_USER="$(container_env MARIADB_USER)"
DB_PASS="$(container_env MARIADB_PASSWORD)"
DB_ROOT_PASS="$(container_env MARIADB_ROOT_PASSWORD)"
DB_NAME="${DB_NAME:-wa_connect}"
DB_USER="${DB_USER:-wa_connect}"
[[ -n "$DB_PASS" ]] || { echo "Unable to determine MARIADB_PASSWORD from db container" >&2; exit 1; }
[[ -n "$DB_ROOT_PASS" ]] || { echo "Unable to determine MARIADB_ROOT_PASSWORD from db container" >&2; exit 1; }

BACKUP_DB="$(manifest_value database)"
BACKUP_COMPOSE="$(manifest_value compose_file)"
[[ -n "$BACKUP_DB" ]] || { echo "Backup manifest does not identify a database" >&2; exit 1; }
[[ "$BACKUP_DB" == "$DB_NAME" ]] || {
  echo "Refusing restore: backup database '$BACKUP_DB' does not match target '$DB_NAME'." >&2
  exit 1
}

MEDIA_PATH="${MEDIA_LOCAL_HOST_PATH:-$(env_value MEDIA_LOCAL_HOST_PATH || printf './storage/inbound-media')}"
[[ "$MEDIA_PATH" = /* ]] || MEDIA_PATH="$ROOT_DIR/${MEDIA_PATH#./}"

printf '\nRestore plan:\n'
printf '  Backup:         %s\n' "$BACKUP_DIR"
printf '  Backup DB:      %s\n' "$BACKUP_DB"
printf '  Backup Compose: %s\n' "${BACKUP_COMPOSE:-unknown}"
printf '  Target DB:      %s\n' "$DB_NAME"
printf '  Target Compose: %s\n' "$COMPOSE_FILE"
printf '  Media path:     %s\n\n' "$MEDIA_PATH"
printf 'This will REPLACE the target database and media. Type RESTORE %s: ' "$DB_NAME"
read -r answer
[[ "$answer" == "RESTORE $DB_NAME" ]] || { echo "Restore cancelled."; exit 2; }

echo "Stopping API and worker to prevent writes..."
docker compose -f "$COMPOSE_FILE" stop api delay-worker
trap 'docker compose -f "$COMPOSE_FILE" start api delay-worker >/dev/null 2>&1 || true' EXIT

echo "Recreating database..."
docker compose -f "$COMPOSE_FILE" exec -T -e MYSQL_PWD="$DB_ROOT_PASS" db mariadb -uroot <<SQL
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
if [[ -f "$BACKUP_DIR/production.env.enc" ]]; then
  echo "Encrypted environment snapshot is available at $BACKUP_DIR/production.env.enc"
  echo "It is intentionally NOT restored automatically. To inspect it safely:"
  echo "  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_ENCRYPTION_PASSPHRASE -in '$BACKUP_DIR/production.env.enc'"
elif [[ -f "$BACKUP_DIR/production.env" ]]; then
  echo "WARNING: unencrypted environment snapshot is present at $BACKUP_DIR/production.env" >&2
fi
