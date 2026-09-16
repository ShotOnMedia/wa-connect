# WA Connect production backups

Backs up the state that cannot simply be recreated from GitHub:

- MariaDB (`mariadb-dump`, transaction-consistent for InnoDB)
- inbound/local media
- production `.env` (encrypted by default)
- production Compose definition
- manifest with Git commit, Alembic revision, sizes and media count
- SHA-256 checksums

Redis is intentionally not backed up: it is runtime/queue state, not the authoritative application database.

## First test

From the WA Connect install directory:

```bash
chmod +x deploy/backup/*.sh
sudo mkdir -p /var/backups/wa-connect
sudo chown "$(id -u):$(id -g)" /var/backups/wa-connect
export BACKUP_DIR=/var/backups/wa-connect
export BACKUP_ENCRYPTION_PASSPHRASE='use-a-long-random-passphrase-kept-outside-this-server'
./deploy/backup/backup.sh
```

Find and verify the newest backup:

```bash
LATEST="$(find /var/backups/wa-connect -mindepth 4 -maxdepth 4 -type d | sort | tail -1)"
./deploy/backup/verify.sh "$LATEST"
cat "$LATEST/manifest.json"
```

Keep the encryption passphrase outside the server (password manager/secrets store). Do not put it in Git.

## Scheduling

A simple production schedule is every 6 hours:

```cron
17 */6 * * * cd /opt/buccaneer && /usr/local/sbin/buccaneer-backup-env /opt/buccaneer/deploy/backup/backup.sh >> /var/log/buccaneer-backup.log 2>&1
```

`/usr/local/sbin/buccaneer-backup-env` should be root-owned mode `0700` and export `BACKUP_DIR`, `BACKUP_ENCRYPTION_PASSPHRASE` and optional S3 credentials before `exec "$@"`. This keeps backup secrets out of the repository and crontab.

Local retention defaults to 30 days and can be changed with `BACKUP_RETENTION_DAYS`.

## S3-compatible off-server copy

The script supports AWS S3, Cloudflare R2, MinIO and similar endpoints through the AWS CLI:

```bash
export BACKUP_S3_ENABLED=true
export BACKUP_S3_BUCKET=buccaneer-backups
export BACKUP_S3_PREFIX=production
export BACKUP_S3_ENDPOINT=https://YOUR-ENDPOINT
export BACKUP_S3_REGION=auto
export BACKUP_S3_ACCESS_KEY=...
export BACKUP_S3_SECRET_KEY=...
```

Configure lifecycle retention on the bucket as an additional safeguard. The local script's retention policy does not delete remote objects.

## Restore test

Do the first restore on a disposable/test installation, not production.

```bash
./deploy/backup/restore.sh /path/to/backup --confirm
```

The restore script verifies checksums first, stops API/worker writes, recreates and imports MariaDB, restores media, then starts the API and delay worker. It deliberately does **not** overwrite the active `.env`; compare/decrypt the archived environment separately.

A backup should not be considered proven until a clean test restore has completed and `/health`, contacts, conversations, flows and representative media have been checked.
