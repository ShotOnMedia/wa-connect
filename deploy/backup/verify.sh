#!/usr/bin/env bash
set -Eeuo pipefail
DIR="${1:?Usage: verify.sh /path/to/backup}"
[[ -d "$DIR" ]] || { echo "Backup directory not found: $DIR" >&2; exit 1; }
cd "$DIR"
sha256sum -c SHA256SUMS
gzip -t database.sql.gz
tar -tzf media.tar.gz >/dev/null
if [[ -f production.env.enc ]]; then
  echo "Encrypted environment archive present."
elif [[ -f production.env ]]; then
  echo "WARNING: environment backup is not encrypted." >&2
else
  echo "Missing environment backup." >&2; exit 1
fi
python3 -m json.tool manifest.json >/dev/null
echo "Backup verification passed: $DIR"
