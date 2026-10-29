# Single entry point for local development and CI. `make check` is the definition of done.
.DEFAULT_GOAL := help
.PHONY: help install format quick lint typecheck test ui-check check schemas build clean

help: ## Show available targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

install: ## Install Python and UI dependencies and git hooks
	uv sync --all-packages --locked
	pnpm -C ui install --frozen-lockfile
	uv run pre-commit install

format: ## Auto-format and apply safe lint fixes
	uv run ruff format
	uv run ruff check --fix
	pnpm -C ui run format

quick: ## Fast Python loop: format check, lint, import layers, types, tests (no coverage)
	uv run ruff format --check
	uv run ruff check
	uv run lint-imports
	uv run pyright
	uv run pytest -x -q --no-cov

lint: ## Lint Python, check import layers and verify the lockfile is current
	uv lock --check
	uv run ruff format --check
	uv run ruff check
	uv run lint-imports

typecheck: ## Type-check Python (strict)
	uv run pyright

test: ## Run Python tests with coverage
	uv run pytest --cov --cov-report=term-missing

ui-check: ## Lint, type-check, test and build the UI
	pnpm -C ui run check

check: lint typecheck test ui-check ## Run everything CI runs

schemas: ## Regenerate the published JSON Schemas in schemas/
	uv run python -m conveyor.model.schema schemas

build: ## Build the Python sdist and wheel
	uv build

clean: ## Remove build and cache artefacts
	rm -rf dist .coverage htmlcov .pytest_cache .ruff_cache src/conveyor/_ui ui/dist
