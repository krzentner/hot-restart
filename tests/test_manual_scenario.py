"""Test the exact scenario that was failing in manual.py."""

import ast
import textwrap
from hot_restart import FindDefPath, build_surrogate_source


def test_manual_py_scenario():
    """Test the exact failure scenario from manual.py where def_path was incorrect."""

    # This is the source after some edits (line numbers shifted by 1)
    source = textwrap.dedent("""
        import hot_restart
        import functools
        
        def outer_fn():
            x, y = 1, 2
            
            @hot_restart.wrap
            @functools.cache
            def inner_fn(s, y):
                # assert False
                print("y", y)
                print("x", x)
                print(s)
            
            inner_fn("test", 1)
            inner_fn("test", 2)
    """)

    tree = ast.parse(source)

    # The original co_firstlineno was 49, but after edit the decorator is at line 50
    # This simulates the off-by-one error
    # In our test, the decorator is at line 8, so we'll test with line 7

    # Old approach would fail to find it
    visitor_old_line = FindDefPath("inner_fn", 7)  # One line before actual decorator
    visitor_old_line.visit(tree)
    result = visitor_old_line.get_best_match()

    # With our overlap-based approach, it should still find it!
    assert result == ["outer_fn", "inner_fn"], (
        f"Expected to find inner_fn, got {result}"
    )

    # Verify that we can build surrogate source with the found path
    try:
        surrogate = build_surrogate_source(source, tree, result, [])
        # If we get here, it worked!
        assert "inner_fn" in surrogate
        print("✓ Successfully built surrogate source for nested function")
    except Exception as e:
        assert False, f"Failed to build surrogate source: {e}"


def test_multiple_edits_scenario():
    """Test scenario where file has been edited multiple times."""

    # Original source
    original = textwrap.dedent("""
        def outer():
            @decorator
            def inner():
                pass
    """)

    # After adding 2 lines at the top
    edited1 = textwrap.dedent("""
        # Added line 1
        # Added line 2
        def outer():
            @decorator
            def inner():
                pass
    """)

    # After removing 1 line from the top
    edited2 = textwrap.dedent("""
        # Added line 2
        def outer():
            @decorator
            def inner():
                pass
    """)

    # Parse all versions
    tree_orig = ast.parse(original)
    tree_edit1 = ast.parse(edited1)
    tree_edit2 = ast.parse(edited2)

    # In original, decorator is at line 3
    # Simulate co_firstlineno = 3

    # Try to find in edited1 (decorator now at line 5)
    visitor1 = FindDefPath("inner", 3)
    visitor1.visit(tree_edit1)
    assert visitor1.get_best_match() == ["outer", "inner"]

    # Try to find in edited2 (decorator now at line 4)
    visitor2 = FindDefPath("inner", 3)
    visitor2.visit(tree_edit2)
    assert visitor2.get_best_match() == ["outer", "inner"]

    print("✓ Handles multiple file edits correctly")


def test_def_path_fallback_removed():
    """Verify that we no longer fall back to [func.__name__] and instead raise exception."""

    from hot_restart import wrap, ReloadException
    import types
    import tempfile
    import os

    # Create a source file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("# Empty file\n")
        f.flush()

        # Create a function that won't be found
        code = compile("def missing(): pass", f.name, "exec")
        func = types.FunctionType(code.co_consts[0], {}, "missing")
        func.__module__ = "test_module"

        # Mock getsourcefile
        import inspect

        original_getsourcefile = inspect.getsourcefile

        def mock_getsourcefile(obj):
            if obj is func or (hasattr(obj, "__wrapped__") and obj.__wrapped__ is func):
                return f.name
            return original_getsourcefile(obj)

        inspect.getsourcefile = mock_getsourcefile

        try:
            # This should raise ReloadException, not fall back to ["missing"]
            try:
                wrap(func)
                assert False, "Expected ReloadException"
            except ReloadException as e:
                assert "Could not get definition path" in str(e)
                print("✓ Correctly raises ReloadException instead of fallback")
        finally:
            inspect.getsourcefile = original_getsourcefile
            os.unlink(f.name)


if __name__ == "__main__":
    test_manual_py_scenario()
    test_multiple_edits_scenario()
    test_def_path_fallback_removed()
    print("\nAll manual scenario tests passed! 🎉")
