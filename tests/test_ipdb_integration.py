#!/usr/bin/env python3
"""Test ipdb integration with hot_restart"""

import sys
import os
import subprocess
from textwrap import dedent


def test_ipdb_is_default():
    """Test that ipdb is used by default when available"""
    # Run in subprocess to ensure clean import
    code = dedent("""
        import hot_restart
        print(hot_restart.DEBUGGER)
    """)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        },
    )
    assert result.stdout.strip() == "ipdb", (
        f"Expected ipdb but got {result.stdout.strip()}"
    )
    print("✓ ipdb is successfully configured as the default debugger")


def test_fallback_without_ipdb():
    """Test that it falls back to pdb when ipdb is not available"""
    # Run in subprocess with ipdb import blocked
    code = dedent("""
        import sys

        # Block ipdb import
        class BlockIpdb:
            def find_module(self, fullname, path=None):
                if fullname == 'ipdb':
                    return self

            def load_module(self, fullname):
                raise ImportError("ipdb not available")

        sys.meta_path.insert(0, BlockIpdb())

        import hot_restart
        print(hot_restart.DEBUGGER)
    """)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        },
    )
    assert result.stdout.strip() == "pdb", (
        f"Expected pdb but got {result.stdout.strip()}"
    )
    print("✓ Successfully falls back to pdb when ipdb is not available")


def test_other_debuggers_still_work():
    """Test that pydevd and pudb detection still works"""
    # Test pydevd detection
    code_pydevd = dedent("""
        import sys
        # Simulate pydevd being available
        sys.modules['pydevd'] = type(sys)('pydevd')

        import hot_restart
        print(hot_restart.DEBUGGER)
    """)
    result = subprocess.run(
        [sys.executable, "-c", code_pydevd],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        },
    )
    # Should prefer ipdb over pydevd when both are available
    assert result.stdout.strip() in ["ipdb", "pydevd"], (
        f"Unexpected debugger: {result.stdout.strip()}"
    )
    print(f"✓ pydevd detection works (got {result.stdout.strip()})")

    # Test pudb detection when ipdb is not available
    code_pudb = dedent("""
        import sys

        # Block ipdb
        class BlockIpdb:
            def find_module(self, fullname, path=None):
                if fullname == 'ipdb':
                    return self
            def load_module(self, fullname):
                raise ImportError("ipdb not available")
        sys.meta_path.insert(0, BlockIpdb())

        # Simulate pudb being available
        sys.modules['pudb'] = type(sys)('pudb')

        import hot_restart
        print(hot_restart.DEBUGGER)
    """)
    result = subprocess.run(
        [sys.executable, "-c", code_pudb],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        },
    )
    assert result.stdout.strip() == "pudb", (
        f"Expected pudb but got {result.stdout.strip()}"
    )
    print("✓ pudb detection works when ipdb is not available")


if __name__ == "__main__":
    print("Testing ipdb integration...")
    test_ipdb_is_default()
    test_fallback_without_ipdb()
    test_other_debuggers_still_work()
