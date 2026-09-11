.PHONY: install dev-install run cli gui test test-gtk test-tray lint format lint-all setup build install-app uninstall-app setup-dev bump-version clean clean-logs

# Переменные
PYTHON := uv run python
CLI := $(PYTHON) cli.py
GUI := $(PYTHON) gui.py


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

# Тесты виджетов GTK4: под xvfb, а при его отсутствии на текущем дисплее.
# Прогон идёт на своей шине сессии: имя `ru.tenga.Proxy` на пользовательской
# шине занимает установленное приложение, и тогда GApplication регистрируется
# прокси к нему — окно создаётся в чужом процессе, а тесты получают None.
# Адрес шины кэшируется при первом обращении к GIO, то есть до старта фикстур,
# поэтому изолировать её можно только снаружи процесса.
# Предупреждения fusermount3 в выводе печатает xdg-desktop-portal сеанса,
# когда к нему подключается новая шина. К тестам они отношения не имеют;
# stderr не глушится, чтобы настоящие ошибки оставались видны.
# Список собирается по маске, а не перечислением: забытый файл иначе молча
# выпадает из прогона.
GTK4_TESTS := $(wildcard tests/test_ui_application.py tests/test_ui_window.py \
	tests/test_ui_widgets_*.py tests/test_ui_pages_*.py)

PYTEST_GTK := uv run pytest -m gtk $(GTK4_TESTS) -p no:cacheprovider --no-cov

test-gtk:
	@if command -v dbus-run-session >/dev/null 2>&1; then \
		BUS="dbus-run-session --"; \
	else \
		echo "dbus-run-session not found: закройте Tenga Proxy перед прогоном"; \
		BUS=""; \
	fi; \
	if command -v xvfb-run >/dev/null 2>&1; then \
		$$BUS xvfb-run -a $(PYTEST_GTK); \
	else \
		echo "xvfb-run not found, using DISPLAY=$$DISPLAY"; \
		GDK_BACKEND=x11 $$BUS $(PYTEST_GTK); \
	fi

# Тесты трея живут отдельно от `test-gtk`: они поднимают собственную шину
# через Gio.TestDBus, а вложить её во внешнюю (dbus-run-session) нельзя —
# libdbus падает с segfault. Здесь шина пользователя и нужна: имя элемента
# трея уникально и с установленным приложением не конфликтует.
TRAY_TESTS := $(wildcard tests/test_ui_tray_*.py)

test-tray:
	uv run pytest -m "" $(TRAY_TESTS) -p no:cacheprovider --no-cov

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

clean-logs:
	rm logs/*.log