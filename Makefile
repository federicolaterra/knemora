.PHONY: setup format format-check lint typecheck test build public-audit check api-dev api-start web-dev web-start db-up db-down db-logs db-migrate db-downgrade llm-build llm-run llm-health llm-benchmark app-start app-stop backup backup-db restore wiki-lint wiki-rebuild eval-basic eval-enterprise

BACKUP_DIR ?=
BACKUP_ARCHIVE ?=
UV_CACHE_DIR ?= $(TMPDIR)/knemora-uv-cache
export UV_CACHE_DIR

setup:
	cd apps/api && uv sync --dev
	cd apps/web && npm ci

format:
	cd apps/api && uv run ruff format .
	cd apps/api && uv run ruff check --fix .
	cd apps/web && npm run format

format-check:
	cd apps/api && uv run ruff format --check .
	cd apps/web && npm run format:check

lint:
	cd apps/api && uv run ruff check .
	cd apps/web && npm run lint

typecheck:
	cd apps/api && uv run mypy app knemora_bootstrap knowledge_agent pharmatrace_ai_agent tests
	cd apps/web && npm run typecheck

test:
	cd apps/api && uv run pytest
	cd apps/web && npm run test

build:
	cd apps/web && npm run build

public-audit:
	cd apps/api && uv run python ../../infrastructure/scripts/audit-public-release.py

check: format-check lint typecheck test build public-audit

api-dev:
	cd apps/api && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

api-start:
	cd apps/api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

web-dev:
	cd apps/web && npm run dev

web-start: build
	cd apps/web && npm run preview -- --host 127.0.0.1 --port 5173

db-up:
	$(MAKE) db-migrate

db-down:
	@echo "SQLite is embedded; there is no database service to stop."

db-logs:
	@echo "SQLite is embedded; use application logs via ./knemora logs."

db-migrate:
	cd apps/api && uv run alembic upgrade head

db-downgrade:
	cd apps/api && uv run alembic downgrade -1

llm-build:
	./infrastructure/scripts/build-llama-cpp-macos.sh

llm-run:
	./infrastructure/scripts/run-llama-server.sh

llm-health:
	./infrastructure/scripts/check-local-llm.sh

llm-benchmark:
	./infrastructure/scripts/benchmark-local-llm.sh

app-start:
	./knemora --no-open start

app-stop:
	./infrastructure/scripts/stop-local-release.sh

backup:
	./infrastructure/scripts/backup-local.sh "$(BACKUP_DIR)" full

backup-db:
	./infrastructure/scripts/backup-local.sh "$(BACKUP_DIR)" database

restore:
	test -n "$(BACKUP_ARCHIVE)"
	./infrastructure/scripts/restore-local.sh "$(BACKUP_ARCHIVE)" --confirm

wiki-lint:
	cd apps/api && uv run python -m app.cli wiki-lint

wiki-rebuild:
	cd apps/api && uv run python -m app.cli wiki-rebuild

eval-basic: llm-health
	cd apps/api && KNEMORA_APP_ENV=evaluation KNEMORA_AUTHENTICATION_REQUIRED=false uv run python -m tests.eval.run_local_eval --dataset tests/eval/datasets/basic-dataset.json --output artifacts/local-eval/basic.json

eval-enterprise: llm-health
	./infrastructure/scripts/run-enterprise-eval.sh
