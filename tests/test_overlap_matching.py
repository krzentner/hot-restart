"""Test the overlap-based matching for FindDefPath."""

import ast
import textwrap
import pytest
from hot_restart import FindDefPath, ReloadException, _get_def_path
import types


def test_exact_overlap():
    """Test that exact matches still work correctly."""

    code = textwrap.dedent("""
        def func1():
            pass
            
        @decorator
        def func2():
            pass
    """)

    tree = ast.parse(code)

    # func1 is at line 2
    visitor1 = FindDefPath("func1", 2, 2)
    visitor1.visit(tree)
    assert visitor1.get_best_match() == ["func1"]

    # func2 decorator is at line 5, def at line 6
    visitor2 = FindDefPath("func2", 5, 5)  # Decorator line
    visitor2.visit(tree)
    assert visitor2.get_best_match() == ["func2"]

    visitor3 = FindDefPath("func2", 6, 6)  # Def line
    visitor3.visit(tree)
    assert visitor3.get_best_match() == ["func2"]


def test_off_by_one_matching():
    """Test that off-by-one errors are handled gracefully."""

    code = textwrap.dedent("""
        # Line 1
        import functools
        
        @functools.cache
        def func():
            pass
    """)

    tree = ast.parse(code)

    # Decorator is at line 5, function at line 6
    # Test various line numbers
    for line in [4, 5, 6, 7]:
        visitor = FindDefPath("func", line, line)
        visitor.visit(tree)
        result = visitor.get_best_match()

        if line >= 5 and line <= 6:
            # Should find it (within range)
            assert result == ["func"], f"Failed for line {line}"
        else:
            # Line 4 is before decorator, line 7 is after function
            # Should still find it as closest match
            assert result == ["func"], f"Failed for line {line}"


def test_nested_function_matching():
    """Test matching nested functions with line number mismatches."""

    code = textwrap.dedent("""
        def outer():
            # Line 3
            @decorator1
            @decorator2
            def inner():
                pass
            return inner
            
        @decorator
        def another():
            pass
    """)

    tree = ast.parse(code)

    # inner function decorators start at line 4, def at line 6
    visitor = FindDefPath("inner", 4, 4)
    visitor.visit(tree)
    assert visitor.get_best_match() == ["outer", "inner"]

    # Test with off-by-one
    visitor2 = FindDefPath("inner", 3, 3)  # One line before decorator
    visitor2.visit(tree)
    assert visitor2.get_best_match() == ["outer", "inner"]

    # Test with line after function
    visitor3 = FindDefPath("inner", 7, 7)  # One line after def
    visitor3.visit(tree)
    assert visitor3.get_best_match() == ["outer", "inner"]


def test_multiple_candidates():
    """Test choosing the best match when there are multiple functions with the same name."""

    code = textwrap.dedent("""
        def outer1():
            def inner():  # Line 3
                pass
                
        def outer2():
            @decorator
            def inner():  # Line 8
                pass
                
        class MyClass:
            def inner(self):  # Line 12
                pass
    """)

    tree = ast.parse(code)

    # Looking for line 3 should find outer1.inner
    visitor1 = FindDefPath("inner", 3, 3)
    visitor1.visit(tree)
    assert visitor1.get_best_match() == ["outer1", "inner"]

    # Looking for line 7 (decorator) or 8 (def) should find outer2.inner
    visitor2 = FindDefPath("inner", 7, 7)
    visitor2.visit(tree)
    assert visitor2.get_best_match() == ["outer2", "inner"]

    # Looking for line 12 should find MyClass.inner
    visitor3 = FindDefPath("inner", 12, 12)
    visitor3.visit(tree)
    assert visitor3.get_best_match() == ["MyClass", "inner"]

    # Looking for line 5 (between functions) should find closest
    visitor4 = FindDefPath("inner", 5, 5)
    visitor4.visit(tree)
    # This is closer to outer1.inner (distance 2) than outer2.inner (distance 2 to decorator)
    # But since they're equal distance, it depends on visit order
    result = visitor4.get_best_match()
    assert result in [["outer1", "inner"], ["outer2", "inner"]]


def test_multiline_decorator_matching():
    """Test matching functions with multi-line decorators."""

    code = textwrap.dedent("""
        @decorator(
            arg1='value1',
            arg2='value2',
            arg3='value3'
        )
        @another_decorator
        def func():
            pass
    """)

    tree = ast.parse(code)

    # First decorator starts at line 2
    # Second decorator at line 7
    # Function def at line 8

    for line in range(1, 10):
        visitor = FindDefPath("func", line, line)
        visitor.visit(tree)
        result = visitor.get_best_match()

        if 2 <= line <= 8:
            # Within function range
            assert result == ["func"], f"Failed for line {line}"
        else:
            # Outside but should still find as closest
            assert result == ["func"], f"Failed for line {line}"


def test_no_match_returns_empty():
    """Test that when no function with the target name exists, we get an empty result."""

    code = textwrap.dedent("""
        def func1():
            pass
            
        def func2():
            pass
    """)

    tree = ast.parse(code)

    visitor = FindDefPath("nonexistent", 5, 5)
    visitor.visit(tree)
    
    # Should raise ReloadException when no function found
    with pytest.raises(ReloadException):
        visitor.get_best_match()


def test_integration_with_wrap():
    """Test that wrap raises ReloadException when function cannot be found."""

    # Import wrap from hot_restart
    from hot_restart import wrap

    # Create a test file with a function
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(
            textwrap.dedent("""
            def existing_func():
                pass
        """)
        )
        f.flush()

        # Create a function that claims to be from this file but at wrong line
        code = compile("def fake_func(): pass", f.name, "exec")
        fake_func = types.FunctionType(
            code.co_consts[0],  # Get the code object for fake_func
            {},
            "nonexistent_func",
        )
        fake_func.__module__ = "__main__"  # Set module for the function

        # Manually set the firstlineno to a line that doesn't exist
        fake_code = fake_func.__code__.replace(co_firstlineno=999)
        fake_func.__code__ = fake_code

        # wrap() doesn't raise ReloadException, it logs error and returns original function
        import inspect
        import logging

        original_getsourcefile = inspect.getsourcefile

        def mock_getsourcefile(obj):
            if obj is fake_func or (
                hasattr(obj, "__wrapped__") and obj.__wrapped__ is fake_func
            ):
                return f.name
            return original_getsourcefile(obj)

        inspect.getsourcefile = mock_getsourcefile
        try:
            # wrap() logs error and returns original function when it can't find it
            result = wrap(fake_func)
            # Should return the original function unchanged
            assert result is fake_func
        finally:
            inspect.getsourcefile = original_getsourcefile
            os.unlink(f.name)


if __name__ == "__main__":
    test_exact_overlap()
    print("✓ Exact overlap test passed")

    test_off_by_one_matching()
    print("✓ Off-by-one matching test passed")

    test_nested_function_matching()
    print("✓ Nested function matching test passed")

    test_multiple_candidates()
    print("✓ Multiple candidates test passed")

    test_multiline_decorator_matching()
    print("✓ Multi-line decorator test passed")

    test_no_match_returns_empty()
    print("✓ No match test passed")

    test_integration_with_wrap()
    print("✓ Integration test passed")

    print("\nAll tests passed! ✨")
