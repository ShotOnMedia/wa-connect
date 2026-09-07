# WA Connect

WA Connect is a self-hosted multi-channel messaging and automation platform for WhatsApp Business and Telegram. It provides live team inboxes, contacts and custom fields, visual automation flows, reusable HTTP APIs, Developer API access, User Input submissions, and configurable Local/S3-compatible media storage.

## Development

```bash
cp .env.example .env
docker compose up --build
```

The development stack uses Vite and Uvicorn reload mode for rapid iteration.

## Production

A separate production stack is provided so production servers do not run the development frontend, source-code bind mounts, or Uvicorn reload mode.

```bash
cp .env.production.example .env
nano .env

docker compose -f docker-compose.prod.yml config >/dev/null
docker compose -f docker-compose.prod.yml up -d --build
```

The production gateway listens on port `8080` by default and is intended to sit behind an HTTPS reverse proxy such as Nginx Proxy Manager.

See [`deploy/PRODUCTION.md`](deploy/PRODUCTION.md) for the complete fresh-install, update, backup, restore, media-storage, and server-migration procedure.

## Health

```text
GET /health
```

A healthy instance returns the application status and version.

## WhatsApp webhook

Configure Meta to use:

```text
GET/POST https://YOUR-HOST/api/v1/webhooks/meta/whatsapp
```

Set `META_VERIFY_TOKEN` to the verification token configured in Meta. In production, configure `META_APP_SECRET` so WA Connect can enforce `X-Hub-Signature-256` verification.

## Current architecture

```text
WhatsApp Cloud API ─┐
                    ├─> FastAPI ─> MariaDB
Telegram Bot API ───┘       │
                            ├─> Redis / delay worker
                            ├─> Local or S3-compatible media storage
                            └─> Vue frontend via Nginx gateway
```

## Branch

Current work: `feature/v0.2.0-telegram-core`
