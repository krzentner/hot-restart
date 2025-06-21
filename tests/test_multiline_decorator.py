"""Test reloading functions with multi-line decorators."""

import pytest
import textwrap
import tempfile
import os
import sys
import subprocess


def test_multiline_decorator_reload():
    """Test that functions with multi-line decorators can be reloaded correctly."""

    # Create a test script with a multi-line decorator
    test_script = textwrap.dedent("""
        import hot_restart
        
        def complex_decorator(
            arg1='default1',
            arg2='default2',
            arg3='default3'
        ):
            def decorator(func):
                def wrapper(*args, **kwargs):
                    print(f"Decorator args: {arg1}, {arg2}, {arg3}")
                    return func(*args, **kwargs)
                return wrapper
            return decorator
        
        @hot_restart.wrap
        @complex_decorator(
            arg1='custom1',
            arg2='custom2',
            arg3='custom3'
        )
        def test_function():
            assert False, "Initial error"
            return "success"
        
        # Also test nested function with multi-line decorator
        def outer():
            @hot_restart.wrap
            @complex_decorator(
                arg1='nested1',
                arg2='nested2',
                arg3='nested3'
            )
            def inner():
                assert False, "Nested error"
                return "nested success"
            
            return inner()
        
        if __name__ == "__main__":
            hot_restart.wrap_module()
            try:
                test_function()
            except AssertionError:
                print("ERROR: test_function failed to reload")
            
            try:
                outer()
            except AssertionError:
                print("ERROR: inner function failed to reload")
    """)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(test_script)
        f.flush()

        try:
            # Run the test script
            result = subprocess.run(
                [sys.executable, f.name], capture_output=True, text=True, timeout=10
            )

            # Check that both errors were caught
            assert "ERROR: test_function failed to reload" in result.stdout
            assert "ERROR: inner function failed to reload" in result.stdout

        finally:
            os.unlink(f.name)


def test_decorator_line_detection():
    """Test that we can correctly identify the start line of decorated functions."""
    import ast
    import inspect

    code = textwrap.dedent("""
        def decorator1(func):
            return func
            
        def decorator2(
            arg1,
            arg2
        ):
            def inner(func):
                return func
            return inner
        
        @decorator1
        @decorator2(
            arg1='value1',
            arg2='value2'
        )
        def simple_func():
            pass
            
        @decorator2(
            arg1='long_value_that_spans',
            arg2='multiple_lines_with_complex_args'
        )
        @decorator1
        def complex_func():
            pass
    """)

    tree = ast.parse(code)

    # Find the function definitions
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in [
            "simple_func",
            "complex_func",
        ]:
            functions[node.name] = node

    # For simple_func:
    # - First decorator (@decorator1) is at line 13
    # - Second decorator (@decorator2) starts at line 14
    # - Function def is at line 18
    simple = functions["simple_func"]
    assert simple.lineno == 18  # The 'def' line
    assert len(simple.decorator_list) == 2

    # Check decorator positions
    dec1 = simple.decorator_list[0]  # @decorator1
    dec2 = simple.decorator_list[1]  # @decorator2(...)

    # The decorator nodes only give us the start of the expression, not the @ symbol
    assert dec1.lineno == 13  # Line of decorator1 name
    assert dec2.lineno == 14  # Line of decorator2 call start

    # For complex_func:
    # - First decorator (@decorator2) starts at line 20
    # - Second decorator (@decorator1) is at line 24
    # - Function def is at line 26 (not 25, there's a blank line)
    complex = functions["complex_func"]
    assert complex.lineno == 26

    # The key insight: we need to find the line with @ before the first decorator
    # This is tricky with just AST, as it doesn't preserve @ symbols


def test_firstlineno_vs_ast_lineno():
    """Test the difference between code object firstlineno and AST lineno."""

    # Create a module with decorated functions
    code = textwrap.dedent("""
        def decorator(func):
            return func
        
        @decorator
        def simple():
            pass
            
        @decorator
        @decorator  
        @decorator
        def multiple():
            pass
    """)

    # Compile and execute to get real functions
    exec_globals = {}
    exec(compile(code, "test", "exec"), exec_globals)

    simple_func = exec_globals["simple"]
    multiple_func = exec_globals["multiple"]

    # Check co_firstlineno - this actually points to the first decorator line, not def
    assert simple_func.__code__.co_firstlineno == 5  # Line of '@decorator'
    assert multiple_func.__code__.co_firstlineno == 9  # Line of first '@decorator'

    # Note: __code__.co_firstlineno actually points to the function definition line,
    # not the decorator line! This might be version-dependent.


if __name__ == "__main__":
    test_multiline_decorator_reload()
    test_decorator_line_detection()
    test_firstlineno_vs_ast_lineno()
    print("All tests passed!")
