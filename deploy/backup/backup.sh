#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${BACKUP_COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${BACKUP_ENV_FILE:-.env}"
BACKUP_ROOT="${BACKUP_DIR:-/var/backups/wa-connect}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DAY="$(date -u +%Y/%m/%d)"
DEST="$BACKUP_ROOT/$DAY/$TIMESTAMP"
TMP="$DEST/.tmp"
mkdir -p "$TMP"

if [[ ! -f "$ENV_FILE" ]]; then echo "Missing $ENV_FILE" >&2; exit 1; fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

DB_NAME="${MARIADB_DATABASE:-wa_connect}"
DB_USER="${MARIADB_USER:-wa_connect}"
DB_PASS="${MARIADB_PASSWORD:?MARIADB_PASSWORD is required}"
MEDIA_PATH="${MEDIA_LOCAL_HOST_PATH:-./storage/inbound-media}"
[[ "$MEDIA_PATH" = /* ]] || MEDIA_PATH="$ROOT_DIR/${MEDIA_PATH#./}"

cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT

echo "[$(date -Is)] Backing up database $DB_NAME"
docker compose -f "$COMPOSE_FILE" exec -T -e MYSQL_PWD="$DB_PASS" db \
  mariadb-dump -u"$DB_USER" --single-transaction --quick --routines --triggers --events "$DB_NAME" \
  | gzip -9 > "$TMP/database.sql.gz"
gzip -t "$TMP/database.sql.gz"

if [[ -d "$MEDIA_PATH" ]]; then
  echo "[$(date -Is)] Archiving media $MEDIA_PATH"
  tar -C "$MEDIA_PATH" -czf "$TMP/media.tar.gz" .
else
  echo "[$(date -Is)] Media path not found; creating empty archive"
  tar -czf "$TMP/media.tar.gz" --files-from /dev/null
fi

cp "$ENV_FILE" "$TMP/production.env"
cp "$COMPOSE_FILE" "$TMP/docker-compose.prod.yml"

GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
ALEMBIC_REVISION="$(docker compose -f "$COMPOSE_FILE" exec -T api alembic current 2>/dev/null | tail -n1 | tr -d '\r' || true)"
DB_BYTES="$(stat -c %s "$TMP/database.sql.gz")"
MEDIA_BYTES="$(stat -c %s "$TMP/media.tar.gz")"
MEDIA_FILES="$(find "$MEDIA_PATH" -type f 2>/dev/null | wc -l | tr -d ' ')"
cat > "$TMP/manifest.json" <<JSON
{
  "created_at_utc": "$TIMESTAMP",
  "git_commit": "$GIT_COMMIT",
  "alembic_revision": "$ALEMBIC_REVISION",
  "database": "$DB_NAME",
  "database_archive_bytes": $DB_BYTES,
  "media_archive_bytes": $MEDIA_BYTES,
  "media_file_count": ${MEDIA_FILES:-0}
}
JSON

( cd "$TMP" && sha256sum database.sql.gz media.tar.gz production.env docker-compose.prod.yml manifest.json > SHA256SUMS )

if [[ -n "${BACKUP_ENCRYPTION_PASSPHRASE:-}" ]]; then
  echo "[$(date -Is)] Encrypting sensitive environment backup"
  openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
    -pass env:BACKUP_ENCRYPTION_PASSPHRASE \
    -in "$TMP/production.env" -out "$TMP/production.env.enc"
  rm "$TMP/production.env"
  ( cd "$TMP" && sha256sum database.sql.gz media.tar.gz production.env.enc docker-compose.prod.yml manifest.json > SHA256SUMS )
elif [[ "${BACKUP_REQUIRE_ENCRYPTION:-true}" == "true" ]]; then
  echo "BACKUP_ENCRYPTION_PASSPHRASE is required when BACKUP_REQUIRE_ENCRYPTION=true" >&2
  exit 1
fi

mkdir -p "$DEST"
find "$TMP" -mindepth 1 -maxdepth 1 -exec mv {} "$DEST/" \;
rmdir "$TMP"
trap - EXIT

( cd "$DEST" && sha256sum -c SHA256SUMS )

echo "[$(date -Is)] Backup verified: $DEST"

if [[ "${BACKUP_S3_ENABLED:-false}" == "true" ]]; then
  command -v aws >/dev/null || { echo "aws CLI required for S3 upload" >&2; exit 1; }
  : "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET required}"
  S3_ARGS=()
  [[ -n "${BACKUP_S3_ENDPOINT:-}" ]] && S3_ARGS+=(--endpoint-url "$BACKUP_S3_ENDPOINT")
  AWS_ACCESS_KEY_ID="${BACKUP_S3_ACCESS_KEY:-${AWS_ACCESS_KEY_ID:-}}" \
  AWS_SECRET_ACCESS_KEY="${BACKUP_S3_SECRET_KEY:-${AWS_SECRET_ACCESS_KEY:-}}" \
  AWS_DEFAULT_REGION="${BACKUP_S3_REGION:-auto}" \
    aws "${S3_ARGS[@]}" s3 cp "$DEST" "s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX:-wa-connect}/$DAY/$TIMESTAMP/" --recursive --only-show-errors
  echo "[$(date -Is)] Off-server upload complete"
fi

find "$BACKUP_ROOT" -type d -mindepth 4 -maxdepth 4 -mtime "+$RETENTION_DAYS" -prune -exec rm -rf {} + 2>/dev/null || true
