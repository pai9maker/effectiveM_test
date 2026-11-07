# EffectiveTube — developer shortcuts.
#
# The full stack runs through Docker: `make up` / `make down`.
# Local development (no Docker) uses the .venv created by `make install`.

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
COMPOSE ?= docker compose
PORT ?= 8081

.DEFAULT_GOAL := help

.PHONY: help install install-docker run test test-integration lint fmt migrate seed up down logs ps shell clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and install dev dependencies
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

run: ## Run the API locally with auto-reload (needs DATABASE_URL/REDIS_URL/S3_*)
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port $(PORT)

test: ## Run unit tests (no external services)
	$(PY) -m pytest -m "not integration"

test-integration: ## Smoke test against a running stack
	ET_SMOKE_URL=http://localhost:$(PORT) $(PY) -m pytest -m integration

lint: ## Lint app, tests and scripts
	$(PY) -m ruff check app tests scripts

fmt: ## Auto-format with ruff
	$(PY) -m ruff format app tests scripts

migrate: ## Apply Alembic migrations to DATABASE_URL
	$(PY) -m alembic upgrade head

seed: ## Load demo users/videos/comments (idempotent)
	$(PY) scripts/seed_demo.py

up: ## Build and start the whole stack on HTTP_PORT (default 8081)
	HTTP_PORT=$(PORT) $(COMPOSE) up -d --build

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow app and worker logs
	$(COMPOSE) logs -f app worker

ps: ## Show container status
	$(COMPOSE) ps

shell: ## Open a shell inside the app container
	$(COMPOSE) exec app bash

clean: ## Remove local caches (keeps .venv and data)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
