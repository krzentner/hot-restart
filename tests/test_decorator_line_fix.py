"""Test the fix for decorator line number matching."""

import ast
import hot_restart


class ImprovedFindDefPath(ast.NodeVisitor):
    """Improved version that correctly handles decorated functions."""

    def __init__(self, target_name: str, target_lineno: int):
        super().__init__()
        self.target_name = target_name
        self.target_lineno = target_lineno
        self.found_def_paths = []
        self.path_now = []

    def generic_visit(self, node: ast.AST):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.path_now.append(node)

            if node.name == self.target_name:
                # Calculate the true start line including decorators
                if hasattr(node, "decorator_list") and node.decorator_list:
                    # Get the first line of the first decorator
                    start_lineno = min(dec.lineno for dec in node.decorator_list)
                else:
                    start_lineno = node.lineno

                end_lineno = getattr(node, "end_lineno", node.lineno)

                # Check if target line is within the full range of the function
                if start_lineno <= self.target_lineno <= end_lineno:
                    self.found_def_paths.append([n.name for n in self.path_now])

            res = super().generic_visit(node)
            self.path_now.pop()
            return res
        else:
            return super().generic_visit(node)


def test_improved_finder():
    """Test that the improved finder handles decorated functions correctly."""

    code = """
import functools

def outer():
    @functools.cache
    def inner():
        pass
    return inner

@functools.lru_cache(
    maxsize=128
)
def standalone():
    pass
"""

    tree = ast.parse(code)

    # Test finding inner function with decorator at line 5
    finder = ImprovedFindDefPath("inner", 5)
    finder.visit(tree)
    assert finder.found_def_paths == [["outer", "inner"]]

    # Test finding standalone function with decorator starting at line 10
    finder2 = ImprovedFindDefPath("standalone", 10)
    finder2.visit(tree)
    assert finder2.found_def_paths == [["standalone"]]

    print("Improved finder tests passed!")


def test_original_finder_fails():
    """Show that the original finder fails on decorated functions."""

    code = """
import functools

def outer():
    @functools.cache
    def inner():
        pass
    return inner
"""

    tree = ast.parse(code)

    # The original finder will fail because it calculates start_lineno
    # AFTER checking the name match
    original_finder = hot_restart.FindDefPath("inner", 5)  # co_firstlineno would be 5
    original_finder.visit(tree)

    # This will be empty because it looks for line 5, but the FunctionDef is at line 6
    print(f"Original finder result: {original_finder.found_def_paths}")
    assert original_finder.found_def_paths == []  # Fails to find it!

    print("Confirmed: Original finder fails on decorated functions")


if __name__ == "__main__":
    test_improved_finder()
    test_original_finder_fails()
