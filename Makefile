.PHONY: help up down restart logs ps build rebuild migrate makemigrations shell-backend shell-frontend shell-db test lint format frontend-install

COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env

help:
	@echo "ZeroKey — common commands"
	@echo ""
	@echo "  make up               Start all services (postgres, redis, qdrant, backend, worker, signer, frontend)"
	@echo "  make down             Stop all services"
	@echo "  make restart          Restart all services"
	@echo "  make logs             Tail logs for all services"
	@echo "  make ps               Show service status"
	@echo "  make build            Build all images"
	@echo "  make rebuild          Rebuild without cache"
	@echo ""
	@echo "  make migrate          Apply Django migrations"
	@echo "  make makemigrations   Create new Django migrations"
	@echo "  make shell-backend    Open a bash shell in the backend container"
	@echo "  make shell-frontend   Open a bash shell in the frontend container"
	@echo "  make shell-db         Open a psql shell against the dev database"
	@echo ""
	@echo "  make test             Run backend tests"
	@echo "  make lint             Run linters (ruff + eslint)"
	@echo "  make format           Apply formatters"

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build

rebuild:
	$(COMPOSE) build --no-cache

migrate:
	$(COMPOSE) exec backend python manage.py migrate

makemigrations:
	$(COMPOSE) exec backend python manage.py makemigrations

shell-backend:
	$(COMPOSE) exec backend bash

shell-frontend:
	$(COMPOSE) exec frontend sh

shell-db:
	$(COMPOSE) exec postgres psql -U zerokey -d zerokey

test:
	$(COMPOSE) exec backend pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint

format:
	cd backend && uv run ruff format . && uv run ruff check --fix .
	cd frontend && npm run format
