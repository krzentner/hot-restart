"""Test for nested function with @hot_restart.wrap and @functools.cache decorators."""

import ast
import pytest
import textwrap
from hot_restart import build_surrogate_source, ReloadException


def test_nested_function_with_decorators_ast_parsing():
    """Test that AST parsing fails for nested functions with decorators when the inner function is empty."""

    # This simulates what happens when hot-restart tries to reload a nested function
    # The error occurs because the transformed AST ends up empty
    source_text = textwrap.dedent("""
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
        
        @hot_restart.wrap
        def main():
            outer_fn()
        
        hot_restart.wrap_module()
        if not hot_restart.is_restarting_module():
            main()
    """)

    # Parse the source
    module_ast = ast.parse(source_text)

    # Try to build surrogate source for the nested function
    # This should fail with "Could not find inner_fn in new source"
    def_path = ["inner_fn"]
    free_vars = []

    with pytest.raises(ReloadException) as exc_info:
        build_surrogate_source(source_text, module_ast, def_path, free_vars)

    assert "Could not find inner_fn in new source" in str(exc_info.value)
