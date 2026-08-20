# WA Connect

WA Connect is a self-hosted WhatsApp Business engagement platform for connecting Meta WhatsApp Business Accounts, receiving and sending messages, operating a live team inbox, and building automated conversation flows.

## v0.1.0 — WhatsApp Core

The first milestone establishes the WhatsApp transport and conversation model:

- Multi-workspace / multi-WABA / multi-phone-number data model
- Meta webhook verification
- Meta webhook signature validation
- Incoming WhatsApp message ingestion
- Contact and conversation creation
- Delivery/read/failure status ingestion
- Conversation/message APIs
- Outbound text messaging through the WhatsApp Cloud API
- MariaDB persistence
- Redis service ready for realtime inbox events and workers

The v0.1.0 target is simple: send a message to a connected WhatsApp number, see it appear in WA Connect, reply from WA Connect, and receive the response in WhatsApp.

## Development

```bash
cp .env.example .env
docker compose up --build
```

The API will be available at `http://localhost:8000`, Swagger at `http://localhost:8000/docs`, and health status at `http://localhost:8000/health`.

### Meta webhook

Configure Meta to use:

```text
GET/POST https://YOUR-HOST/api/v1/webhooks/meta/whatsapp
```

Set `META_VERIFY_TOKEN` to the verification token configured in Meta. Set `META_APP_SECRET` to enforce `X-Hub-Signature-256` verification. In development only, signature verification is bypassed when no app secret is configured.

## Current architecture

```text
Meta WhatsApp Cloud API
        │
        ▼
     FastAPI
        │
   ┌────┴────┐
   ▼         ▼
MariaDB     Redis
   │
   ▼
Vue Live Inbox (next)
```

## Branch

Current work: `feature/v0.1.0-whatsapp-core`
