# ZeroKey

> Enterprise-grade, SME-friendly e-invoicing for the Malaysian market. A product of **Symprio Sdn Bhd**, hosted at **zerokey.symprio.com**.
>
> **Drop the PDF. Drop the Keys.**

## Repository layout

```
.
├── CLAUDE.md          Entry point for Claude Code sessions
├── docs/              Strategy, architecture, and product specifications
├── backend/           Django 5 monolith (Python 3.12 via uv)
├── frontend/          Next.js 14 + TypeScript + shadcn/ui
├── infra/             docker-compose and (later) Terraform
└── .github/           CI workflows
```

## Documentation

The product is documented in [`docs/`](./docs). Start with [`docs/START_HERE.md`](./docs/START_HERE.md), then [`docs/PRODUCT_VISION.md`](./docs/PRODUCT_VISION.md). The full index is in [`docs/README.md`](./docs/README.md).

## Local development

```bash
cp .env.example .env
make up          # starts postgres, redis, qdrant, backend, worker, signer, frontend
make migrate     # applies Django migrations
make test        # runs the backend test suite
make down        # stops everything
```

The backend runs on http://localhost:8000, the frontend on http://localhost:3000.

## What's running where

| Service  | Port | Image                     |
| -------- | ---- | ------------------------- |
| backend  | 8000 | local build (`backend/`)  |
| frontend | 3000 | local build (`frontend/`) |
| postgres | 5432 | postgres:16-alpine        |
| redis    | 6379 | redis:7-alpine            |
| qdrant   | 6333 | qdrant/qdrant:latest      |

The Celery worker and signing-service worker share the backend image with different commands.

## Project status

Phase 1 complete; Phase 2 in flight. End-to-end working: sign up, drop a PDF,
watch it auto-extract and auto-structure into LHDN-shape fields with a
hash-chained audit trail.

- Forward-looking plan → [`docs/ROADMAP.md`](./docs/ROADMAP.md)
- What's actually shipped → [`docs/BUILD_LOG.md`](./docs/BUILD_LOG.md)
