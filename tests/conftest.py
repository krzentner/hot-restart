"""pytest configuration for hot_restart tests."""

import os
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--debugger",
        action="store",
        default="auto",
        choices=["auto", "pdb", "ipdb"],
        help="Debugger to use for tests (default: auto)",
    )


@pytest.fixture
def debugger(request):
    """Return the debugger to use for tests."""
    return request.config.getoption("--debugger")


@pytest.fixture(autouse=True)
def configure_debugger(debugger):
    """Configure hot_restart to use the specified debugger."""
    if debugger != "auto":
        os.environ["HOT_RESTART_DEBUGGER"] = debugger
    else:
        # Let hot_restart auto-detect
        os.environ.pop("HOT_RESTART_DEBUGGER", None)
    yield
    # Clean up
    os.environ.pop("HOT_RESTART_DEBUGGER", None)
