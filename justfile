# hot-restart development commands

# Default command - show available commands
default:
    @just --list

# Setup development environment
setup:
    uv sync --group dev --group recommended

# Run all tests with default debugger (ipdb if available)
test: setup
    uv run pytest tests/ --isolate

# Run all tests with pdb
test-pdb: setup
    HOT_RESTART_DEBUGGER=pdb uv run pytest tests/ --isolate

# Run all tests with ipdb
test-ipdb: setup
    uv run pytest tests/ --isolate

# Run pytest tests with both debuggers
test-both: setup
    @echo "Testing with pdb..."
    HOT_RESTART_DEBUGGER=pdb uv run pytest tests/ --isolate
    @echo "Testing with ipdb..."
    HOT_RESTART_DEBUGGER=ipdb uv run pytest tests/ --isolate

# Run ALL tests including pytest and standalone scripts
test-all: setup
    @echo "Testing with pdb..."
    HOT_RESTART_DEBUGGER=pdb uv run pytest tests/ --isolate
    @echo "Testing with ipdb..."
    HOT_RESTART_DEBUGGER=ipdb uv run pytest tests/ --isolate

# Run a specific test (can specify file::test_name or just test_name)
test-one TEST: setup
    uv run pytest tests/ -k "{{TEST}}" -v --isolate

# Run a specific test with pdb
test-one-pdb TEST: setup
    HOT_RESTART_DEBUGGER=pdb uv run pytest tests/ -k "{{TEST}}" -v --isolate

# Run tests without isolation (for AST tests or debugging)
test-no-isolate: setup
    uv run pytest tests/ --no-isolate

# Run a specific test without isolation
test-one-no-isolate TEST: setup
    uv run pytest tests/ -k "{{TEST}}" -v --no-isolate

# Run linter
lint: setup
    uv run ruff check hot_restart.py

# Run linter with auto-fix
lint-fix: setup
    uv run ruff check hot_restart.py --fix

# Build package
build: setup
    uv run flit build

# Install development dependencies (alias for setup)
install-dev: setup

# Run ipdb integration tests
test-ipdb-integration: setup
    uv run python tests/test_ipdb_integration.py


# Clean up temporary files and caches
clean:
    rm -rf __pycache__ .pytest_cache .venv
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    find . -type f -name ".coverage" -delete
    find . -type d -name "*.egg-info" -exec rm -rf {} +
    find . -type d -name ".ipynb_checkpoints" -exec rm -rf {} +
