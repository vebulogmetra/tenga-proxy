.PHONY: help install dev-install run cli gui test lint format lint-all setup build install-app uninstall-app setup-dev bump-version clean

# Переменные
PYTHON := uv run python
CLI := $(PYTHON) cli.py
GUI := $(PYTHON) gui.py

help:
	@echo "Доступные команды:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:
	uv sync

dev-install:
	uv sync --extra dev

run:
	$(GUI)

cli:
	$(CLI) --help

# CLI commands
parse:
	$(CLI) parse $(LINK)

add:
	$(CLI) add $(LINK)

list:
	$(CLI) ls

remove:
	$(CLI) rm $(ID)

run-proxy:
	$(CLI) run $(LINK)

version:
	$(CLI) ver

# Build and installation
setup:
	$(CLI) setup

build:
	$(CLI) build

install-app:
	$(CLI) install

uninstall-app:
	$(CLI) install --uninstall

setup-dev:
	$(CLI) setup-dev

bump-version:
	$(CLI) bump-version $(VERSION)

# Code quality
lint:
	$(CLI) lint

lint-fix:
	$(CLI) lint --fix

format:
	$(CLI) format

format-check:
	$(CLI) format --check

lint-all:
	$(CLI) lint-all

# Testing
test:
	uv run pytest

test-cov:
	uv run pytest --cov=src --cov-report=term-missing --cov-report=html

# Utilities
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf __pycache__/
	find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
