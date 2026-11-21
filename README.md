# My Agentic

A personal, self-hosted AI office for one person. Your own AI agents remember, learn
skills, run tasks and workflows, read your files, browse the web and use your computer. Everything
you connect lives in one place: all your email accounts and your WhatsApp number.

Forked from Agentic Office, without the multi-company parts (organizations, members, roles,
staff, Prima Secure, the guide and tutorials). One owner, one company, every AI feature.

## What it does

- **Inbox**: connect as many email accounts as you like, all in one page with an account
  switcher (or "All inboxes"):
  - Microsoft 365 / Outlook.com (Microsoft sign-in; work and personal accounts)
  - Gmail (Google sign-in)
  - anything else over IMAP + SMTP with an app password (Gmail, Yahoo, iCloud, cPanel, Zoho...)

  Read, search, mark read, reply, reply all, forward, save drafts and move to trash. "Ask AI"
  summarizes an email, drafts a reply, improves your draft or writes a new email.
- **Your agents and your email**: tools `inbox_accounts`, `inbox_check`, `inbox_search`,
  `inbox_read`, `inbox_draft` and `inbox_send`. Sending asks for your approval by default; turn
  it to "allow" per agent on the agent's page if you trust it.
- **WhatsApp (WAHA)**: chat as your connected number from the web (chats, messages, replies,
  quotes). Your agent answers you there. In a group, mention the number (or reply to it) with a
  task and the agent does it and answers in the group. Per chat, choose when the AI answers:
  - Off
  - Only me (the default): only your own linked number
  - Everyone in the chat: anyone who mentions the number. They get a plain, tool-less answer
    with no access to your private data.
- Everything else from Agentic Office: agents and the agent builder, chat, tasks and approvals,
  workflows, schedules, the brain (memory and wiki), skills that improve themselves, the
  Library with search inside documents, documents and templates, forms and reports, meetings
  and minutes, your own computers (PC agent), the agent browser, the code sandbox, Telegram,
  phone notifications, Microsoft 365 calendar and Teams, MCP tools and the AI Engine (providers,
  model groups, usage and cost).

## Run it locally

```bash
docker compose up -d --build
# http://localhost:8500  (dev mode creates test logins; see apps/api/agentic/seed.py)
```

Develop:

```bash
docker compose up -d postgres valkey temporal
cd apps/api && uv sync && uv run alembic upgrade head
uv run uvicorn agentic.api.main:app --reload --port 8501
uv run python -m agentic.workflows.worker
cd apps/web && corepack pnpm install && corepack pnpm dev   # http://localhost:5173
```

Tests: `cd apps/api && uv run pytest -q` (TEST_PG / TEST_VALKEY point at a test Postgres and
Valkey). Web: `cd apps/web && corepack pnpm typecheck && corepack pnpm test`.

## Deploy (VPS)

The production server runs it as the compose project `my-agentic` in `/opt/my-agentic`, behind
the server's Orxies proxy at https://my.oriondesk.space (upstream `127.0.0.1:8720`).

```bash
cd /opt/my-agentic
cp .env.vps.example .env   # once: fill in every secret (python3 deploy/scripts/gen-secrets.py)
./deploy/scripts/deploy-vps.sh
```

The deploy script backs up, pulls, builds, runs migrations (the api applies them at start),
starts everything and refuses to finish if any port is published on a public address.

## First steps after deploy

1. Open the site and create the owner account (first visit shows the setup page).
2. **AI Engine**: add a provider key (Anthropic, OpenAI, OpenRouter, Azure...) and set the
   `smart` and `fast` groups.
3. **Inbox**: add your email accounts.
   - IMAP/SMTP: works at once with an app password.
   - Microsoft: needs an Azure app registration (Settings > Channels > Microsoft 365). Set
     "Accounts in any organizational directory and personal Microsoft accounts". The redirect
     URI is `https://my.oriondesk.space/api/integrations/microsoft/callback`.
   - Gmail sign-in: needs a Google OAuth client (Settings > Channels > Gmail). The redirect URI
     is `https://my.oriondesk.space/api/integrations/google/callback`. Gmail also works over
     IMAP with an app password.
4. **Settings > Channels > WhatsApp**: add WAHA (the defaults point at the bundled container)
   and scan the QR code with the phone whose number the AI will use. Then link your own
   personal number (Link my account, send the code to the connected number from your phone),
   so the bot knows it is you.
5. Create your assistant agent (Agents > New, or My assistants).
