# hot-restart development commands

# Default command - show available commands
default:
    @just --list

# Run all tests with default debugger (ipdb if available)
test:
    uv run pytest tests/

# Run all tests with pdb
test-pdb:
    HOT_RESTART_DEBUGGER=pdb uv run pytest tests/

# Run all tests with ipdb
test-ipdb:
    HOT_RESTART_DEBUGGER=ipdb uv run pytest tests/

# Run pytest tests with both debuggers
test-both:
    @echo "Testing with pdb..."
    HOT_RESTART_DEBUGGER=pdb uv run pytest tests/
    @echo "Testing with ipdb..."
    HOT_RESTART_DEBUGGER=ipdb uv run pytest tests/

# Run ALL tests including pytest and standalone scripts
test-all:
    @echo "Testing with pdb..."
    HOT_RESTART_DEBUGGER=pdb uv run pytest tests/
    @echo "Testing with ipdb..."
    HOT_RESTART_DEBUGGER=ipdb uv run pytest tests/

# Run a specific test (can specify file::test_name or just test_name)
test-one TEST:
    uv run pytest tests/ -k "{{TEST}}" -v

# Run a specific test with pdb
test-one-pdb TEST:
    HOT_RESTART_DEBUGGER=pdb uv run pytest tests/ -k "{{TEST}}" -v

# Run linter
lint:
    uv run ruff check hot_restart.py

# Run linter with auto-fix
lint-fix:
    uv run ruff check hot_restart.py --fix

# Build package
build:
    uv run flit build

# Install development dependencies
install-dev:
    uv pip install -r dev-requirements.txt
    uv pip install --group recommended

# Run ipdb integration tests
test-ipdb-integration:
    uv run python tests/test_ipdb_integration.py


# Clean up temporary files and caches
clean:
    rm -rf __pycache__ .pytest_cache .venv
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    find . -type f -name ".coverage" -delete
    find . -type d -name "*.egg-info" -exec rm -rf {} +
    find . -type d -name ".ipynb_checkpoints" -exec rm -rf {} +
