"""Test that FindDefPath should be tolerant of small line number mismatches."""

import ast
import textwrap
import pytest
from hot_restart import FindDefPath


def test_line_number_mismatch_decorated_function():
    """Test the case where co_firstlineno doesn't exactly match decorator lines."""

    # Original source when function was defined
    original_source = textwrap.dedent("""
        import hot_restart
        import functools
        
        def outer_fn():
            x, y = 1, 2
            
            @hot_restart.wrap
            @functools.cache  
            def inner_fn(s, y):
                print("y", y)
                print("x", x)
                print(s)
            
            inner_fn("test", 1)
    """)

    # Modified source with an extra line at the top
    modified_source = textwrap.dedent("""
        # This line was added after initial load
        import hot_restart
        import functools
        
        def outer_fn():
            x, y = 1, 2
            
            @hot_restart.wrap
            @functools.cache  
            def inner_fn(s, y):
                print("y", y)
                print("x", x)
                print(s)
            
            inner_fn("test", 1)
    """)

    # Parse both versions
    original_tree = ast.parse(original_source)
    modified_tree = ast.parse(modified_source)

    # Find inner_fn line numbers in original
    for node in ast.walk(original_tree):
        if isinstance(node, ast.FunctionDef) and node.name == "inner_fn":
            original_first_dec = min(dec.lineno for dec in node.decorator_list)
            print(f"Original inner_fn first decorator at line: {original_first_dec}")

    # Now try to find it in modified source using original line number
    # This simulates co_firstlineno pointing to the old line number
    finder = FindDefPath("inner_fn", original_first_dec)
    finder.visit(modified_tree)

    # This will fail because of the line offset!
    print(f"Found paths: {finder.found_def_paths}")
    assert finder.found_def_paths == []  # Not found due to line mismatch

    # The improved version should handle this better
    print("\nThis demonstrates why we need tolerance for line number mismatches")


def test_tolerance_window():
    """Test that we should look within a small window around target_lineno."""

    source = textwrap.dedent("""
        import functools
        
        @functools.cache
        def func1():
            pass
            
        # Some comments
        # More comments
        
        @functools.lru_cache(
            maxsize=128
        )
        def func2():
            pass
    """)

    tree = ast.parse(source)

    # func1's decorator is at line 4
    # func2's decorator is at line 11

    # Test exact matches work
    finder1 = FindDefPath("func1", 4)
    finder1.visit(tree)
    assert finder1.get_best_match() == ["func1"]

    finder2 = FindDefPath("func2", 11)
    finder2.visit(tree)
    assert finder2.get_best_match() == ["func2"]

    # Test off-by-one scenarios - with overlap matching, these should now work!
    finder3 = FindDefPath("func1", 3)  # One line before decorator
    finder3.visit(tree)
    assert finder3.get_best_match() == ["func1"]  # Found with distance-based matching

    finder4 = FindDefPath("func2", 10)  # One line before decorator
    finder4.visit(tree)
    assert finder4.get_best_match() == ["func2"]  # Found with distance-based matching

    print("New FindDefPath handles off-by-one with distance matching")


class TolerantFindDefPath(ast.NodeVisitor):
    """Version with tolerance for small line number differences."""

    def __init__(self, target_name: str, target_lineno: int, tolerance: int = 2):
        super().__init__()
        self.target_name = target_name
        self.target_lineno = target_lineno
        self.tolerance = tolerance
        self.found_def_paths = []
        self.path_now = []

    def generic_visit(self, node: ast.AST):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.path_now.append(node)

            if node.name == self.target_name:
                # Calculate the true start including decorators
                if hasattr(node, "decorator_list") and node.decorator_list:
                    start_lineno = min(dec.lineno for dec in node.decorator_list)
                else:
                    start_lineno = node.lineno

                end_lineno = getattr(node, "end_lineno", node.lineno)

                # Check with tolerance
                if (
                    start_lineno - self.tolerance
                    <= self.target_lineno
                    <= end_lineno + self.tolerance
                ):
                    self.found_def_paths.append([n.name for n in self.path_now])

            res = super().generic_visit(node)
            self.path_now.pop()
            return res
        else:
            return super().generic_visit(node)


def test_tolerant_finder():
    """Test the tolerant finder handles mismatches better."""

    source = textwrap.dedent("""
        # Line 1
        import functools
        
        @functools.cache
        def func():
            pass
    """)

    tree = ast.parse(source)

    # Decorator is actually at line 5
    # Test that tolerant finder can find it even with slight mismatches

    tolerant = TolerantFindDefPath("func", 3, tolerance=2)  # Looking 2 lines early
    tolerant.visit(tree)
    assert tolerant.found_def_paths == [["func"]]  # Found with tolerance!

    tolerant2 = TolerantFindDefPath("func", 7, tolerance=2)  # Looking at def line
    tolerant2.visit(tree)
    assert tolerant2.found_def_paths == [["func"]]  # Also found

    print("Tolerant finder successfully handles line number mismatches!")


if __name__ == "__main__":
    test_line_number_mismatch_decorated_function()
    print()
    test_tolerance_window()
    print()
    test_tolerant_finder()
