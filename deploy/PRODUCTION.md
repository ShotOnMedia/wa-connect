# WA Connect production deployment

This guide covers a fresh production installation and moving an existing WA Connect instance to another server.

## 1. Server requirements

Recommended starting point:

- Debian 12 or Ubuntu 24.04
- Docker Engine with Docker Compose plugin
- Git
- 2+ vCPU
- 4+ GB RAM
- a public DNS name such as `waconnect.example.com`
- an HTTPS reverse proxy in front of WA Connect (for example Nginx Proxy Manager)

Install Docker and Git:

```bash
apt update
apt install -y ca-certificates curl git openssl
curl -fsSL https://get.docker.com | sh

docker --version
docker compose version
```

## 2. Clone the application

```bash
mkdir -p /opt
cd /opt
git clone git@github.com:ShotOnMedia/wa-connect.git
cd wa-connect
git checkout feature/v0.2.0-telegram-core
```

When a stable release branch/tag becomes available, production servers should track that instead of the development branch.

## 3. Create the production environment

```bash
cp .env.production.example .env
```

Generate secrets:

```bash
openssl rand -hex 32   # MEDIA_SETTINGS_ENCRYPTION_KEY
openssl rand -hex 32   # MARIADB_PASSWORD
openssl rand -hex 32   # MARIADB_ROOT_PASSWORD
openssl rand -hex 32   # META_VERIFY_TOKEN
```

Edit `.env` and set at minimum:

- `PUBLIC_BASE_URL`
- `CORS_ORIGINS`
- `MEDIA_SETTINGS_ENCRYPTION_KEY`
- `MARIADB_PASSWORD`
- `MARIADB_ROOT_PASSWORD`
- `DATABASE_URL` using the same MariaDB user/password/database
- `META_VERIFY_TOKEN`
- `BOOTSTRAP_ADMIN_EMAIL`
- `BOOTSTRAP_ADMIN_PASSWORD`

`MEDIA_SETTINGS_ENCRYPTION_KEY` must remain stable for the lifetime of the installation. It encrypts saved S3 credentials. If it changes, previously stored encrypted credentials cannot be decrypted.

For Docker production, keep `INBOUND_MEDIA_DIR=/app/storage/inbound-media`. `MEDIA_LOCAL_HOST_PATH` controls where those files live on the host. A useful production value is:

```dotenv
MEDIA_LOCAL_HOST_PATH=/opt/wa-connect-data/inbound-media
```

Create it before first start:

```bash
mkdir -p /opt/wa-connect-data/inbound-media
```

## 4. Start WA Connect

Validate the Compose file first:

```bash
docker compose -f docker-compose.prod.yml config >/dev/null
```

Then build and start:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The API startup automatically runs:

```text
alembic upgrade head
```

so database migrations are applied before Uvicorn starts.

Check status:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 api
docker compose -f docker-compose.prod.yml logs --tail=100 frontend
docker compose -f docker-compose.prod.yml logs --tail=100 delay-worker
```

Health check from the host:

```bash
curl http://127.0.0.1:8080/health
```

Expected response resembles:

```json
{"status":"ok","version":"0.2.0"}
```

## 5. Reverse proxy and HTTPS

By default WA Connect exposes its production gateway on host port `8080`.

Configure the public reverse proxy to send:

```text
https://waconnect.example.com -> http://WA_CONNECT_SERVER_IP:8080
```

Enable WebSocket support if your reverse-proxy product offers the option, preserve the host header, and issue a valid TLS certificate.

The WA Connect production gateway sends `/api/` to FastAPI and all other requests to the compiled Vue frontend.

## 6. First login and channel setup

The bootstrap administrator is created only when needed from:

- `BOOTSTRAP_ADMIN_EMAIL`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `BOOTSTRAP_ADMIN_NAME`

After login, configure the required channels and settings in the UI.

For Telegram, register/re-register each bot with the new public WA Connect URL so Telegram points at the correct webhook.

For WhatsApp, configure Meta's webhook callback to the new public installation and use the same verification token configured in `.env`.

## 7. Media storage

WA Connect supports Local Storage and S3/S3-compatible storage.

For Local Storage, files persist outside the container through `MEDIA_LOCAL_HOST_PATH`.

For S3-compatible storage, configure the provider from **Settings -> Media Storage**. S3 credentials are encrypted using `MEDIA_SETTINGS_ENCRYPTION_KEY`.

Inbound Live Chat media and User Input image captures use the selected storage provider.

## 8. Updating production

```bash
cd /opt/wa-connect
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Then check:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 api
```

## 9. Backups

### MariaDB

Create a logical backup:

```bash
cd /opt/wa-connect
docker compose -f docker-compose.prod.yml exec -T db \
  mariadb-dump -u root -p"$MARIADB_ROOT_PASSWORD" --single-transaction --routines --triggers wa_connect \
  > wa-connect-$(date +%F-%H%M).sql
```

If the shell does not already contain the `.env` variables, load them first:

```bash
set -a
. ./.env
set +a
```

### Local media

If Local Storage is selected, back up the directory referenced by `MEDIA_LOCAL_HOST_PATH`.

Example:

```bash
tar czf wa-connect-media-$(date +%F-%H%M).tar.gz /opt/wa-connect-data/inbound-media
```

### S3 media

If S3 is selected, media is already external to the WA Connect host. Use the bucket provider's backup/versioning/lifecycle facilities as appropriate.

### Encryption key

Back up `.env` securely, especially `MEDIA_SETTINGS_ENCRYPTION_KEY`. A database backup containing encrypted S3 credentials is not sufficient without that key.

## 10. Moving an existing installation to another server

To clone the complete instance rather than create a fresh environment:

1. Stop or temporarily quiesce writes on the old instance.
2. Export MariaDB.
3. Copy `.env` securely to the new server. Keep the same `MEDIA_SETTINGS_ENCRYPTION_KEY`.
4. If Local Storage is used, copy the media directory to the new `MEDIA_LOCAL_HOST_PATH`.
5. Clone the same WA Connect code/ref on the new server.
6. Start the database and restore the dump.
7. Start the complete production stack.
8. Change DNS/reverse-proxy routing to the new server.
9. Re-register Telegram webhook URLs if the public hostname changed.
10. Update Meta's WhatsApp callback if the public hostname changed.

A simple restore into a fresh production database can be done after starting the DB service:

```bash
cd /opt/wa-connect
docker compose -f docker-compose.prod.yml up -d db redis

docker compose -f docker-compose.prod.yml exec -T db \
  mariadb -u root -p"$MARIADB_ROOT_PASSWORD" wa_connect < wa-connect-backup.sql

docker compose -f docker-compose.prod.yml up -d --build
```

## 11. Useful operations

Restart the API only:

```bash
docker compose -f docker-compose.prod.yml restart api
```

Rebuild API and worker after backend changes:

```bash
docker compose -f docker-compose.prod.yml up -d --build api delay-worker
```

Rebuild the frontend only:

```bash
docker compose -f docker-compose.prod.yml up -d --build frontend
```

Follow logs:

```bash
docker compose -f docker-compose.prod.yml logs -f api
```

Stop without deleting persistent data:

```bash
docker compose -f docker-compose.prod.yml down
```

Do **not** use `down -v` on production unless you intentionally want to delete the MariaDB and Redis Docker volumes.
