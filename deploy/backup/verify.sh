#!/usr/bin/env bash
set -Eeuo pipefail

DIR="${1:?Usage: verify.sh /path/to/backup}"
[[ -d "$DIR" ]] || { echo "Backup directory not found: $DIR" >&2; exit 1; }
DIR="$(cd "$DIR" && pwd)"
cd "$DIR"

for required in SHA256SUMS database.sql.gz media.tar.gz docker-compose.yml manifest.json; do
  [[ -f "$required" ]] || { echo "Missing required backup file: $required" >&2; exit 1; }
done

sha256sum -c SHA256SUMS
gzip -t database.sql.gz
tar -tzf media.tar.gz >/dev/null

if [[ -f production.env.enc ]]; then
  echo "Encrypted environment archive present."
elif [[ -f production.env ]]; then
  echo "WARNING: environment backup is not encrypted." >&2
else
  echo "Missing environment backup." >&2
  exit 1
fi

python3 -m json.tool manifest.json >/dev/null
python3 - manifest.json <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
required = ("created_at_utc", "git_commit", "compose_file", "database", "database_archive_bytes", "media_archive_bytes", "media_file_count")
missing = [key for key in required if key not in data]
if missing:
    raise SystemExit("Manifest missing required fields: " + ", ".join(missing))
if not data["database"]:
    raise SystemExit("Manifest database field is empty")
PY

echo "Backup verification passed: $DIR"
