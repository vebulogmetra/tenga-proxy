# Repository Guidelines

## Always respond on Russian language.

## Project Structure & Module Organization
Main code lives in `src/`, split by responsibility:
- `src/core/`: app context, xray process management, monitoring, logging.
- `src/fmt/`: share-link/subscription parsing and protocol models.
- `src/db/`: JSON-backed profiles and app settings storage.
- `src/ui/`: GTK app, tray, windows, dialogs.
- `src/sys/`: system proxy, VPN, single-instance logic.
- `src/sub/`: subscription update flow.

Entrypoints are `cli.py` (CLI) and `gui.py` (desktop app). Tests are in `tests/` (`test_*.py`). Dev/runtime assets and binaries are in `assets/` and `core/bin/`.

## Build, Test, and Development Commands
- `uv sync --extra dev`: install dependencies including test/lint tools.
- `uv run python gui.py`: run GUI locally.
- `uv run python cli.py --help`: inspect CLI commands.
- `make test` or `uv run pytest`: run test suite.
- `make test-cov`: run tests with coverage (terminal + `htmlcov/`).
- `make lint`, `make lint-fix`: run Ruff checks / auto-fix.
- `make format`, `make format-check`: apply/check formatting.
- `uv run python cli.py build`: build AppImage into `dist/`.

## Coding Style & Naming Conventions
Python 3.11+; 4-space indentation; max line length 100. Formatting/linting is enforced via Ruff (`pyproject.toml`), with import sorting aligned to first-party package `src`.

Use:
- `snake_case` for functions/modules/variables.
- `PascalCase` for classes (`AppContext`, `XrayManager` style).
- `UPPER_SNAKE_CASE` for constants.

Keep new modules consistent with existing domain split (`core`, `fmt`, `db`, `ui`, `sys`, `sub`).

## Testing Guidelines
Framework: `pytest` with `pytest-cov`. Discovery is configured for `tests/test_*.py`. Prefer focused unit tests close to touched behavior (parser logic, config/store updates, monitor/system interactions). Run `make test-cov` before opening a PR and verify no regressions in covered paths.

## Commit & Pull Request Guidelines
History shows concise, imperative commit messages (e.g., `Add log manager integration`), plus version-tag commits (`0.9.0`) for releases. Follow:
- One logical change per commit.
- Subject line in imperative mood; optional scope (`core:`, `ui:`) is welcome.

For PRs, include:
- Problem and solution summary.
- Linked issue/task (if available).
- Test evidence (`make test`, lint/format status).
- Screenshots/GIFs for UI changes (`src/ui/*`, dialogs, tray behavior).

## Security & Configuration Tips
Do not commit secrets or personal subscription links. Respect config locations: dev mode uses local `core/` and `logs/`; packaged mode uses user config dirs. Ensure `core/bin/xray` is executable and sourced from a trusted release.
