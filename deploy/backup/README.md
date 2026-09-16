# WA Connect backups

Backs up state that cannot simply be recreated from GitHub:

- MariaDB (`mariadb-dump`, transaction-consistent for InnoDB)
- inbound/local media
- application `.env` snapshot (encrypted by default)
- selected Compose definition
- manifest with Git commit, Alembic revision, sizes and media count
- SHA-256 checksums

Redis is intentionally not backed up: it is runtime/queue state, not the authoritative application database.

The scripts do **not** `source` the Docker application `.env` as shell code. Database credentials are read from the resolved running `db` container.

## Development

From `/opt/wa-connect`, the default Compose file is `docker-compose.yml`:

```bash
export BACKUP_DIR=/var/backups/wa-connect
export BACKUP_ENCRYPTION_PASSPHRASE='use-a-long-random-passphrase-kept-outside-this-server'
./deploy/backup/backup.sh
```

## Production

The live `/opt/buccaneer` deployment uses `docker-compose.prod.yml`, so production backup and restore commands must select it explicitly:

```bash
BACKUP_COMPOSE_FILE=docker-compose.prod.yml ./deploy/backup/backup.sh
```

and for a restore:

```bash
BACKUP_COMPOSE_FILE=docker-compose.prod.yml \
  ./deploy/backup/restore.sh /path/to/backup --confirm
```

## Verification

Find and verify the newest backup:

```bash
LATEST="$(find /var/backups/wa-connect -mindepth 4 -maxdepth 4 -type d | sort | tail -1)"
./deploy/backup/verify.sh "$LATEST"
cat "$LATEST/manifest.json"
```

Verification checks the SHA-256 manifest, gzip database archive, media tar archive, environment snapshot presence, JSON manifest syntax, and required manifest fields.

## Encryption

Keep `BACKUP_ENCRYPTION_PASSPHRASE` outside the repository, preferably in a password manager/secrets store and in a root-owned backup runtime configuration on the server.

With the default `BACKUP_REQUIRE_ENCRYPTION=true`, a backup fails rather than retaining an unencrypted environment snapshot when no passphrase is available.

The environment snapshot is intentionally **not** restored automatically. It may contain deployment-specific secrets and configuration that should be reviewed before replacing the active environment.

To inspect an encrypted snapshot without writing plaintext to disk:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -pass env:BACKUP_ENCRYPTION_PASSPHRASE \
  -in /path/to/backup/production.env.enc
```

## Restore safety

Do the first restore on a disposable/test installation, not production.

The restore script:

- verifies the backup before changing anything
- requires the running database container to be available
- checks that the database named in `manifest.json` matches the target database
- displays both the backup and target Compose file names
- requires an explicit confirmation containing the database name, for example `RESTORE wa_connect`
- stops API/worker writes before recreating the database
- restores MariaDB and media
- deliberately does not overwrite the active `.env`

After restoring, verify `/health`, contacts, conversations, flows and representative media before reopening normal traffic.

## Scheduling

A simple production schedule is every 6 hours:

```cron
17 */6 * * * cd /opt/buccaneer && /usr/local/sbin/buccaneer-backup-env /opt/buccaneer/deploy/backup/backup.sh >> /var/log/buccaneer-backup.log 2>&1
```

`/usr/local/sbin/buccaneer-backup-env` should be root-owned mode `0700` and export at least:

```bash
export BACKUP_COMPOSE_FILE=docker-compose.prod.yml
export BACKUP_DIR=/var/backups/wa-connect
export BACKUP_ENCRYPTION_PASSPHRASE='...'
exec "$@"
```

It may also export optional S3 credentials. This keeps backup secrets out of the repository and crontab.

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
