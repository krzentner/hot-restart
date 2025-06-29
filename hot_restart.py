"""Restart debugging your program in the function that failed.

Basic usage:

import hot_restart; hot_restart.wrap_module()

See README.md for more detailed usage instructions.
"""

__version__ = "0.2.4"

import threading
import sys
import logging
import functools
import pdb
import inspect
import tokenize
import tempfile
import ast
from typing import Any, Optional
import types
import re
import os
from dataclasses import dataclass
import dis

# Check debug logging once at module load
DEBUG_LOG = os.environ.get("HOT_RESTART_DEBUG_LOG", "")


@dataclass
class Candidate:
    """Represents a candidate function match with overlap scoring."""

    path: list[str]
    score: int
    start: int
    end: int


def setup_logger():
    logger = logging.getLogger("hot-restart")
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter("%(levelname)s (%(name)s): %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Add file handler if debug log is enabled
    debug_log_path = DEBUG_LOG
    if debug_log_path:
        file_handler = logging.FileHandler(debug_log_path, mode="a")
        detailed_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
        )
        file_handler.setFormatter(detailed_formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    else:
        logger.setLevel(logging.INFO)
    return logger


_LOGGER = setup_logger()


def _debug_dump_reload_info(
    func_name,
    def_path,
    source_file,
    source_text,
    module_ast,
    transformed_ast,
    surrogate_source,
    error=None,
):
    """Dump detailed reload information when debug logging is enabled."""
    if DEBUG_LOG:
        _LOGGER.debug("=" * 80)
        _LOGGER.debug(f"RELOAD ATTEMPT: {func_name}")
        _LOGGER.debug(f"Def Path: {def_path}")
        _LOGGER.debug(f"Source File: {source_file}")
        _LOGGER.debug(f"Source Text Length: {len(source_text)} chars")
        _LOGGER.debug(f"Module AST:\n{ast.dump(module_ast, indent=2)}")
        if transformed_ast:
            _LOGGER.debug(f"Transformed AST:\n{ast.dump(transformed_ast, indent=2)}")
        if surrogate_source:
            _LOGGER.debug(f"Surrogate Source:\n{surrogate_source}")
        if error:
            _LOGGER.debug(f"Error: {error}")
        _LOGGER.debug("=" * 80)


# Global configuration

## Automatically reload code on continue.
RELOAD_ON_CONTINUE = True

## Print the help message when first opening pdb
PRINT_HELP_MESSAGE = True

## Causes program to exit.
PROGRAM_SHOULD_EXIT = False

## Reload all wrapped functions and classes on any continue.
RELOAD_ALL_ON_CONTINUE = False


def _choose_debugger():
    # Check environment variable first
    env_debugger = os.environ.get("HOT_RESTART_DEBUGGER", "").lower()
    if env_debugger:
        if env_debugger == "debugpy":
            # debugpy's backend is pydevd, so that's what we use in this case
            env_debugger = "pydevd"
        if env_debugger not in ("pdb", "ipdb", "pudb", "pydevd"):
            raise ValueError(f"Unsupported HOT_RESTART_DEBUGGER {env_debugger}")
        return env_debugger

    # Prefer "graphical" debuggers if already imported.
    # The user is unlikely to have imported these on accident
    if "pydevd" in sys.modules:
        # This is the backend for debugpy (VS Code)
        return "pydevd"
    elif "pudb" in sys.modules:
        # A curses gui debugger
        return "pudb"

    # No graphical debugger, see if we can import ipdb, and use it if so
    try:
        import ipdb  # noqa: F401

        return "ipdb"
    except ImportError:
        pass

    # Default to pdb
    return "pdb"


## Debugger to use
DEBUGGER = _choose_debugger()
_DEBUG_ORIGINAL_PATH_FOR_RELOADED_CODE = DEBUGGER not in ("pdb", "ipdb")


# Magic attribute names added by decorators
_HOT_RESTART_ALREADY_WRAPPED = "_hot_restart_already_wrapped"
_HOT_RESTART_NO_WRAP = "_hot_restart_no_wrap"

_CHECK_FOR_SOURCE_ON_LOAD = False

# Thread locals used during reload
_HOT_RESTART_MODULE_RELOAD_CONTEXT = threading.local()
_HOT_RESTART_MODULE_RELOAD_CONTEXT.val = {}

_HOT_RESTART_SURROGATE_RESULT = "HOT_RESTART_SURROGATE_RESULT"

_HOT_RESTART_IN_SURROGATE_CONTEXT = threading.local()
_HOT_RESTART_IN_SURROGATE_CONTEXT.val = None

_IS_RESTARTING_MODULE = threading.local()
_IS_RESTARTING_MODULE.val = False

# This needs to be settable from the debugger UI
# Unfortunately we have no idea what thread the debugger will set this from
_EXIT_THIS_FRAME = None


class HotRestartPdb(pdb.Pdb):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _cmdloop(self) -> None:
        self.cmdloop()
        if PROGRAM_SHOULD_EXIT:
            pdb.Pdb.set_quit(self)

    def set_quit(self):
        reraise()
        print(
            "Exitting debugging one level. Call hot_restart.exit() to exit the program."
        )
        super().set_quit()


def exit():
    """It can sometimes be hard to exit hot_restart programs.
    Calling this function (and exiting any debugger sessions) will
    short-circuit any hot_restart wrappers.
    """
    global PROGRAM_SHOULD_EXIT
    PROGRAM_SHOULD_EXIT = True


def reraise():
    """Calling the function will cause the current exception to be
    re-raised in the current thread when the debuger exits."""
    global _EXIT_THIS_FRAME
    _EXIT_THIS_FRAME = True


# Mapping from definition paths to temp files of reloaded code.
# Temp files are allocated to hold surrogate source so that the debugger can
# still show correct code listings even after the files are updated.
# One source file is allocated per function.
_TMP_SOURCE_FILES = {}

# Mapping from surrogate source filenames to original filenames
# Used to find the original source in cases of reloading an nested inner
# function after the outer function has been reloaded
_TMP_SOURCE_ORIGINAL_MAP = {}


class ReloadException(ValueError):
    """Exception when hot-restart fails to reload a function."""

    pass


class FindDefPath(ast.NodeVisitor):
    """Given a target name and line number of a definition, find a definition path.

    This gives a more durable identity to a function than its original line number.
    """

    def __init__(
        self, target_name: str, target_first_lineno: int, target_last_lineno: int
    ):
        super().__init__()
        self.target_name = target_name
        self.target_first_lineno = target_first_lineno
        self.target_last_lineno = target_last_lineno
        self.found_def_paths = []
        self.path_now = []
        # Track candidates with their overlap scores
        self.candidates = []

    def generic_visit(self, node: ast.AST) -> Any:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.path_now.append(node)
            current_path = [n.name for n in self.path_now]
            if DEBUG_LOG:
                _LOGGER.debug(
                    f"FindDefPath visiting {node.name} at line {node.lineno}, current path: {current_path}"
                )

            if node.name == self.target_name:
                # Calculate the full range including decorators
                if hasattr(node, "decorator_list") and node.decorator_list:
                    start_lineno = min(dec.lineno for dec in node.decorator_list)
                else:
                    start_lineno = node.lineno
                end_lineno = getattr(node, "end_lineno", node.lineno)

                # Calculate overlap with target line range
                target_start = self.target_first_lineno
                target_end = self.target_last_lineno

                # Calculate overlap between [start_lineno, end_lineno] and [target_start, target_end]
                overlap_start = max(start_lineno, target_start)
                overlap_end = min(end_lineno, target_end)

                if overlap_start <= overlap_end:
                    # There is overlap - score based on overlap size
                    overlap_size = overlap_end - overlap_start + 1
                    overlap_score = overlap_size
                else:
                    # No direct overlap, but record distance for potential fuzzy matching
                    # Negative score based on distance
                    if self.target_last_lineno < start_lineno:
                        overlap_score = -abs(start_lineno - self.target_last_lineno)
                    else:
                        overlap_score = -abs(self.target_first_lineno - end_lineno)

                self.candidates.append(
                    Candidate(
                        path=[node.name for node in self.path_now],
                        score=overlap_score,
                        start=start_lineno,
                        end=end_lineno,
                    )
                )

                if DEBUG_LOG:
                    _LOGGER.debug(
                        f"FindDefPath candidate {self.target_name} at path {current_path}:"
                    )
                    _LOGGER.debug(f"    target_lineno = {self.target_lineno}")
                    _LOGGER.debug(f"    start_lineno = {start_lineno}")
                    _LOGGER.debug(f"    end_lineno = {end_lineno}")
                    _LOGGER.debug(f"    overlap_score = {overlap_score}")

            res = super().generic_visit(node)
            self.path_now.pop()
            return res
        else:
            return super().generic_visit(node)

    def get_best_match(self) -> list[str]:
        """Get the best matching path based on overlap scores."""
        if not self.candidates:
            raise ReloadException(
                f"Could not find {self.target_name} in its source file"
            )

        # Sort by score (highest first)
        sorted_candidates = sorted(self.candidates, key=lambda x: x.score, reverse=True)
        best = sorted_candidates[0]

        if DEBUG_LOG and len(sorted_candidates) > 1:
            _LOGGER.debug(f"FindDefPath multiple candidates for {self.target_name}:")
            for i, cand in enumerate(sorted_candidates):
                _LOGGER.debug(
                    f"  {i + 1}. {cand.path} (score={cand.score}, lines {cand.start}-{cand.end})"
                )
            _LOGGER.debug(f"  Selected: {best.path}")
        return best.path


class SuperRewriteTransformer(ast.NodeTransformer):
    """
    Rewrite super() -> super(<classname>, <first argument>)
    This ensures that adding a super() call does not result in a new closure,
    but instead a (probably global) lookup of the classname.
    This solves more problems than it causes (it causes a minor source
    mismatch, but allows adding new calls to super() in non-nested classes).
    """

    def __init__(self) -> None:
        super().__init__()
        self.class_name_stack = []
        self.first_arg_stack = []

    def visit_ClassDef(self, node: ast.ClassDef):
        self.class_name_stack.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self.class_name_stack.pop()
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        saved_arg = False
        if len(node.args.args) >= 1:
            saved_arg = True
            self.first_arg_stack.append(node.args.args[0].arg)

        try:
            self.generic_visit(node)
        finally:
            if saved_arg:
                self.first_arg_stack.pop()
        return node

    def visit_Call(self, node: ast.Call):
        if getattr(node.func, "id", None) == "super" and len(node.args) == 0:
            try:
                node.args = [
                    ast.Name(self.class_name_stack[-1]),
                    ast.Name(self.first_arg_stack[-1]),
                ]
            except IndexError:
                _LOGGER.error(f"Could not rewrite super() call at line {node.lineno}")
        self.generic_visit(node)
        return node


class SurrogateTransformer(ast.NodeTransformer):
    """Transforms module source ast into a module only containing a target
    function and any surrounding scopes necessary for the compile to build the
    right closure for that target.
    This module is compiled and executed in the context of the original module,
    preventing side effects.

    This is necessary for super() to work, since it implicitly is a closure
    over __class__.
    """

    def __init__(self, target_path: list[str], free_vars: list[str]):
        super().__init__()
        self.target_path = target_path
        self.depth = 0
        self.original_lineno = 0
        self.original_end_lineno = 0
        self.free_vars = free_vars

    def visit_Module(self, node: ast.Module) -> ast.Module:
        if DEBUG_LOG:
            _LOGGER.debug(
                f"SurrogateTransformer.visit_Module: starting depth={self.depth}, target_path={self.target_path}"
            )
        result = ast.Module(
            body=self.visit_body(node.body), type_ignores=node.type_ignores
        )
        if DEBUG_LOG:
            _LOGGER.debug(
                f"SurrogateTransformer.visit_Module: result body length={len(result.body)}"
            )
        return result

    def visit_ClassDef(self, node: ast.ClassDef) -> Optional[ast.ClassDef]:
        if node.name != self.target_path[self.depth]:
            return None

        self.depth += 1
        new_body = self.visit_body(node.body)
        self.depth -= 1

        return ast.ClassDef(
            name=node.name,
            bases=[],
            keywords=node.keywords,
            body=new_body,
            decorator_list=[],
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Optional[list[ast.AST]]:
        if DEBUG_LOG:
            _LOGGER.debug(
                f"SurrogateTransformer.visit_FunctionDef: node={node.name}, depth={self.depth}, target_path={self.target_path}"
            )

        if node.name != self.target_path[self.depth]:
            return None

        self.depth += 1
        if self.depth == len(self.target_path):
            # Found target function
            self.original_lineno = node.lineno
            self.original_end_lineno = node.end_lineno

            # Create closure variable bindings
            freevar_bindings = ast.parse(
                "\n".join(
                    f"{var} = 'HOT_RESTART_LOST_CLOSURE'" for var in self.free_vars
                )
            ).body

            # Create function definition
            func_def = ast.FunctionDef(
                name=node.name,
                args=node.args,
                body=node.body,
                decorator_list=node.decorator_list,
                returns=node.returns,
            )

            # Set result in globals
            set_result = ast.parse(
                f"globals().setdefault('HOT_RESTART_SURROGATE_RESULT', {node.name})"
            ).body

            self.depth -= 1
            return freevar_bindings + [func_def] + set_result
        else:
            # Create stub function for parent scope
            new_body = self.visit_body(node.body)
            new_body.append(
                ast.Return(value=ast.Name(self.target_path[self.depth], ctx=ast.Load()))
            )
            stub_func = ast.FunctionDef(
                name=node.name,
                args=[],
                body=new_body,
                decorator_list=[],
                returns=node.returns,
            )
            self.depth -= 1
            return [stub_func] + ast.parse(f"{node.name}()").body

    def visit_body(self, nodes: list[ast.stmt]) -> list[ast.stmt]:
        new_nodes = []
        for node in nodes:
            result = self.visit(node)
            if isinstance(result, list):
                new_nodes.extend(result)
            elif result is not None:
                new_nodes.append(result)
        return new_nodes

    def generic_visit(self, node: ast.AST) -> Optional[list[ast.stmt]]:
        if hasattr(node, "body") or hasattr(node, "orelse"):
            body = getattr(node, "body", [])
            orelse = getattr(node, "orelse", [])
            return self.visit_body(body + orelse)
        return None


_SUPER_CALL = re.compile(r"super\(([^)]*)\)")
_EMPTY_SUPER_CALL = re.compile(r"super\(\s*\)")


def _merge_sources(
    *,
    original_source: str,
    surrogate_source: str,
    original_start_lineno: int,
    original_end_lineno: int,
    surrogate_start_lineno: int,
    surrogate_end_lineno: int,
):
    """Combine whitespace from original source with other text from non-surrogate source.
    This is the light-weight alternative to using a concrete syntax tree, that is
    only sufficient because of the very minimal AST re-writing performed inside of the target function.
    Namely, it only re-writes zero argument super() calls into the two argument form, and does not re-write any other code.
    """
    original_lines = original_source.splitlines()
    surrogate_lines = surrogate_source.splitlines()
    original_chars = "\n".join(
        original_lines[original_start_lineno:original_end_lineno]
    )
    surrogate_chars = "\n".join(
        surrogate_lines[surrogate_start_lineno:surrogate_end_lineno]
    )

    super_args = _SUPER_CALL.search(surrogate_chars)
    if super_args is not None:
        args = super_args.groups(1)[0]
        replacement = f"super({args})"
        # Replace every empty super() call with the replacement
        merged_chars = _EMPTY_SUPER_CALL.sub(replacement, original_chars)
    else:
        merged_chars = original_chars
    missing_line_count = max(0, original_start_lineno - surrogate_start_lineno)
    merged_text = "\n".join(
        [
            "\n" * max(missing_line_count - 1, 0),
            "\n".join(surrogate_lines[:surrogate_start_lineno]),
            "".join(merged_chars),
            "\n".join(surrogate_lines[surrogate_end_lineno:]),
        ]
    )
    return merged_text


class LineNoResetter(ast.NodeTransformer):
    def visit(self, node):
        node.lineno = None
        node.end_lineno = None
        return super().visit(node)


class FindTargetNode(ast.NodeVisitor):
    def __init__(self, target_path: list[str]):
        self.target_path = target_path
        self.target_nodes = []
        self.current_path = []

    def visit(self, node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.current_path.append(node.name)
            if self.current_path == self.target_path:
                self.target_nodes.append(node)
            try:
                res = super().visit(node)
            finally:
                self.current_path.pop()
            return res
        else:
            return super().visit(node)


def build_surrogate_source(source_text, module_ast, def_path, free_vars):
    """Builds a source file containing the definition of def_path at the same
    lineno as in the ast, with the same parent class(es), but with all other
    lines empty.
    """
    if DEBUG_LOG:
        _LOGGER.debug(
            f"build_surrogate_source: def_path={def_path}, free_vars={free_vars}"
        )
        _LOGGER.debug(f"build_surrogate_source: source_text length={len(source_text)}")

    SuperRewriteTransformer().visit(module_ast)
    trans = SurrogateTransformer(target_path=def_path, free_vars=free_vars)

    new_ast = trans.visit(module_ast)
    new_ast = ast.fix_missing_locations(new_ast)
    transformed_source = ast.unparse(new_ast)

    if DEBUG_LOG:
        _LOGGER.debug(
            f"build_surrogate_source: transformed AST body length={len(new_ast.body)}"
        )
        _LOGGER.debug(
            f"build_surrogate_source: transformed source length={len(transformed_source)}"
        )

    # Re-parse to get updated lineno
    # TODO: Find a way to do this without reparsing
    node_finder = FindTargetNode(def_path)
    node_finder.visit(ast.parse(transformed_source))
    target_nodes = node_finder.target_nodes

    def_path_str = ".".join(def_path)
    if len(target_nodes) == 0:
        msg = f"Could not find {def_path_str} in new source"
        _LOGGER.error(msg)
        _LOGGER.error("=== BEGIN SOURCE TEXT ===")
        _LOGGER.error(source_text)
        _LOGGER.error("=== END SOURCE TEXT ===")
        _LOGGER.error(ast.dump(new_ast, indent=2))
        _LOGGER.error("=== BEGIN TRANSFORMED SOURCE TEXT ===")
        _LOGGER.error(transformed_source)
        _LOGGER.error("=== END TRANSFORMED SOURCE TEXT ===")

        if DEBUG_LOG:
            # Dump comprehensive debug info
            _debug_dump_reload_info(
                func_name=def_path_str,
                def_path=def_path,
                source_file="<unknown>",
                source_text=source_text,
                module_ast=module_ast,
                transformed_ast=new_ast,
                surrogate_source=transformed_source,
                error=msg,
            )

        raise ReloadException(msg)
    if len(target_nodes) > 1:
        _LOGGER.error(f"Overlapping definitions of {def_path_str} in source")
    target_node = target_nodes[0]
    merged_source = _merge_sources(
        original_source=source_text,
        surrogate_source=transformed_source,
        original_start_lineno=trans.original_lineno,
        original_end_lineno=trans.original_end_lineno,
        surrogate_start_lineno=target_node.lineno,
        surrogate_end_lineno=target_node.end_lineno,
    )
    return merged_source


@functools.cache
def _parse_src(source: str) -> ast.AST:
    return ast.parse(source)


def _get_class_def_path(cls) -> Optional[list[str]]:
    """Get the definition path for a class."""
    source_filename = inspect.getsourcefile(cls)
    if DEBUG_LOG:
        _LOGGER.debug(
            f"_get_class_def_path: class={cls!r}, source_filename={source_filename}"
        )

    if source_filename == "<string>" or source_filename is None:
        raise ReloadException(f"{cls!r} was generated and has no source")

    with open(source_filename, "r") as f:
        source_content = f.read()
    module_ast = _parse_src(source_content)

    # Get class source lines for line number
    try:
        source_lines, start_lineno = inspect.getsourcelines(cls)
        # Calculate end line number
        end_lineno = start_lineno + len(source_lines) - 1
    except (OSError, TypeError) as e:
        _LOGGER.error(f"Could not get source lines for {cls!r}: {e}")
        return None

    visitor = FindDefPath(
        target_name=cls.__name__,
        target_first_lineno=start_lineno,
        target_last_lineno=end_lineno,
    )
    visitor.visit(module_ast)

    # Use the new get_best_match method
    def_path = visitor.get_best_match()

    if DEBUG_LOG:
        _LOGGER.debug(f"_get_class_def_path: best match def_path={def_path}")

    return def_path


def _get_function_def_path(func, _recursive=False) -> Optional[list[str]]:
    """Get the definition path for a function."""
    unwrapped_func = inspect.unwrap(func)
    if unwrapped_func is not func:
        _LOGGER.debug("Finding def path of wrapped function.")
        try:
            _LOGGER.debug(
                f"function {func!r} has source file {inspect.getsourcefile(func)}"
            )
        except TypeError:
            _LOGGER.debug(f"function {func!r} has no source file")

        _LOGGER.debug(
            f"unwrapped function {unwrapped_func!r} has source file {inspect.getsourcefile(unwrapped_func)}"
        )

    source_filename = inspect.getsourcefile(unwrapped_func)
    if DEBUG_LOG:
        _LOGGER.debug(
            f"_get_function_def_path: func={func!r}, source_filename={source_filename}"
        )
        _LOGGER.debug(
            f"_get_function_def_path: func.__name__={unwrapped_func.__name__}, lineno={unwrapped_func.__code__.co_firstlineno}"
        )

    if source_filename == "<string>" or source_filename is None:
        raise ReloadException(f"{func!r} was generated and has no source")
    with open(source_filename, "r") as f:
        source_content = f.read()
    module_ast = _parse_src(source_content)
    func_name = unwrapped_func.__name__
    func_start_lineno = unwrapped_func.__code__.co_firstlineno
    inst_positions = [
        int(inst.starts_line)
        for inst in dis.get_instructions(unwrapped_func)
        if getattr(inst, "starts_line", None)
    ]
    if inst_positions:
        func_last_lineno = max(inst_positions)
    else:
        func_last_lineno = func_start_lineno + 1
    visitor = FindDefPath(
        target_name=func_name,
        target_first_lineno=func_start_lineno,
        target_last_lineno=func_last_lineno,
    )
    visitor.visit(module_ast)

    # Use the new get_best_match method
    def_path = visitor.get_best_match()

    if DEBUG_LOG:
        _LOGGER.debug(f"_get_function_def_path: best match def_path={def_path}")

    if not def_path:
        if not _recursive:
            _LOGGER.error(f"Could not find definition of {unwrapped_func!r}")
            _LOGGER.debug(ast.dump(module_ast, indent=2))
        return None
    # Check that we can build a surrogate source for this func
    if _CHECK_FOR_SOURCE_ON_LOAD:
        build_surrogate_source(
            source_content, module_ast, def_path, unwrapped_func.__code__.co_freevars
        )
    return def_path


def _get_def_path(func, _recursive=False) -> Optional[list[str]]:
    """Get the definition path for a function or class.

    This is a dispatcher that delegates to the appropriate specialized function.
    """
    if inspect.isclass(func):
        return _get_class_def_path(func)
    else:
        return _get_function_def_path(func, _recursive=_recursive)


def reload_function(def_path: list[str], func):
    """Takes in a definition path and function, and returns a new version of
    that function reloaded from source.

    This _does not_ cause the function to be reloaded in place (that's
    significantly more difficult to do, especially in a thread safe way).
    """

    def_str = ".".join(def_path)
    unwrapped_func = inspect.unwrap(func)
    source_filename = inspect.getsourcefile(unwrapped_func)
    original_source_filename = source_filename
    source_filename = _TMP_SOURCE_ORIGINAL_MAP.get(source_filename, source_filename)

    if DEBUG_LOG:
        _LOGGER.debug(f"reload_function: def_path={def_path}, def_str={def_str}")
        _LOGGER.debug(
            f"reload_function: original_source_filename={original_source_filename}"
        )
        _LOGGER.debug(f"reload_function: mapped_source_filename={source_filename}")
        _LOGGER.debug(
            f"reload_function: _TMP_SOURCE_ORIGINAL_MAP={_TMP_SOURCE_ORIGINAL_MAP}"
        )

    _LOGGER.debug(f"Reloading {def_str} from {source_filename}")
    try:
        with open(source_filename, "r") as f:
            all_source = f.read()
    except (OSError, FileNotFoundError, tokenize.TokenError) as e:
        _LOGGER.error(
            f"Could not read source for {func!r} from {source_filename}: {e!r}"
        )
        return None
    try:
        src_ast = ast.parse(all_source, filename=source_filename)
    except SyntaxError as e:
        _LOGGER.error(f"Could not parse source for {func!r}: {e!r}")
        return None

    module = inspect.getmodule(func)
    if source_filename is None:
        # Probably used in an interactive session or something, which
        # we don't know how to get source code from.
        _LOGGER.error(f"Could not reload {func!r}: No known source file")
        return None
    try:
        surrogate_src = build_surrogate_source(
            all_source, src_ast, def_path, unwrapped_func.__code__.co_freevars
        )
    except ReloadException:
        return None

    # Create a "flattened filename" to use as a temp file suffix.
    # This way we avoid needing to clean up any temporary directories.
    flat_filename = (
        source_filename.replace("/", "_").replace("\\", "_").replace(":", "_")
    )
    temp_source = tempfile.NamedTemporaryFile(suffix=flat_filename, mode="w")
    temp_source.write(surrogate_src)
    temp_source.flush()
    _LOGGER.debug("=== SURROGATE SOURCE BEGIN ===")
    _LOGGER.debug(surrogate_src)
    _LOGGER.debug("=== SURROGATE SOURCE END ===")

    surrogate_filename = temp_source.name
    if _DEBUG_ORIGINAL_PATH_FOR_RELOADED_CODE:
        _LOGGER.warning(f"Faking path of generated source for {func!r}")
        _LOGGER.warning(f"Real generated code source is in {temp_source.name}")
        surrogate_filename = source_filename
    code = compile(surrogate_src, surrogate_filename, "exec")
    ctxt = dict(vars(module))

    if _HOT_RESTART_SURROGATE_RESULT in ctxt:
        del ctxt[_HOT_RESTART_SURROGATE_RESULT]
        _LOGGER.error("Leftover result from surrogate load")

    try:
        _HOT_RESTART_IN_SURROGATE_CONTEXT.val = ctxt
        exec(code, ctxt, ctxt)
    finally:
        _HOT_RESTART_IN_SURROGATE_CONTEXT.val = None
    raw_func = ctxt.get(_HOT_RESTART_SURROGATE_RESULT, None)
    if raw_func is None:
        _LOGGER.error(f"Could not reload {func!r}: Could not find {def_str}")
        return None
    if raw_func is inspect.unwrap(raw_func):
        # We are wrapping directly, patch up closure.
        closure = unwrapped_func.__closure__
        if closure is None:
            closure = ()
        n_freevars = len(raw_func.__code__.co_freevars)
        if not isinstance(closure, tuple) or n_freevars != len(closure):
            _LOGGER.error(
                f"New {def_str} has closure cells {closure!r}"
                f" but {n_freevars} cells were expected"
            )
            _LOGGER.error(f"Closures in {def_str} lost")
            closure = tuple(
                [types.CellType("HOT_RESTART_LOST_CLOSURE") for _ in range(n_freevars)]
            )
        new_func = types.FunctionType(
            raw_func.__code__,
            func.__globals__,
            raw_func.__name__,
            raw_func.__defaults__,
            # If the new source "closes over" new variables, then those will
            # turn into confusing "global not defined" messages.
            # TODO(krzentner): Find a way to print a good error message in this case.
            closure,
        )
    else:
        # We already warn about this on wrap, no need to repeat on reload
        _LOGGER.debug(
            f"wrap was not innermost decorator of {def_str}, closures will not work"
        )
        new_func = raw_func
    # Keep new temp file alive until function is reloaded again
    _TMP_SOURCE_FILES[def_str] = temp_source
    _TMP_SOURCE_ORIGINAL_MAP[temp_source.name] = source_filename
    return new_func


def reload_class(def_path: list[str], cls):
    """Takes in a definition path and class, and returns a new version of
    that class reloaded from source.
    """
    def_str = ".".join(def_path)

    # Get source file information
    source_filename = inspect.getsourcefile(cls)
    source_filename = _TMP_SOURCE_ORIGINAL_MAP.get(source_filename, source_filename)

    if DEBUG_LOG:
        _LOGGER.debug(f"reload_class: def_path={def_path}, def_str={def_str}")
        _LOGGER.debug(f"reload_class: source_filename={source_filename}")

    _LOGGER.debug(f"Reloading class {def_str} from {source_filename}")

    try:
        with open(source_filename, "r") as f:
            all_source = f.read()
    except (OSError, FileNotFoundError) as e:
        _LOGGER.error(
            f"Could not read source for {cls!r} from {source_filename}: {e!r}"
        )
        return None

    try:
        src_ast = ast.parse(all_source, filename=source_filename)
    except SyntaxError as e:
        _LOGGER.error(f"Could not parse source for {cls!r}: {e!r}")
        return None

    module = inspect.getmodule(cls)
    if source_filename is None:
        _LOGGER.error(f"Could not reload {cls!r}: No known source file")
        return None

    # Find the class definition in the AST
    finder = FindTargetNode(def_path)
    finder.visit(src_ast)

    if not finder.target_nodes:
        _LOGGER.error(f"Could not find class {def_str} in source")
        return None

    # Create a module containing just the class definition
    # We compile and exec the whole module to preserve imports and context
    code = compile(all_source, source_filename, "exec")

    # Execute in module context to get the new class
    ctxt = dict(vars(module))
    exec(code, ctxt, ctxt)

    # Navigate the def_path to find the reloaded class
    new_cls = ctxt
    for part in def_path:
        new_cls = new_cls.get(part)
        if new_cls is None:
            _LOGGER.error(f"Could not find {def_str} in reloaded module")
            return None

    return new_cls


def reload_all_wrapped():
    """Reload all wrapped functions and classes from their source files."""
    _LOGGER.info("Reloading all wrapped functions and classes")

    # Reload all functions
    for def_path_str, base_func in list(_FUNC_BASE.items()):
        # Skip module prefix in def_path
        parts = def_path_str.split(".")
        module_name = parts[0]
        def_path = parts[1:]

        new_func = reload_function(def_path, base_func)
        if new_func is not None:
            _FUNC_NOW[def_path_str] = new_func
            _LOGGER.debug(f"Reloaded function {def_path_str}")
        else:
            _LOGGER.warning(f"Failed to reload function {def_path_str}")

    # Reload all classes
    for def_path_str, base_cls in list(_CLASS_BASE.items()):
        # Skip module prefix in def_path
        parts = def_path_str.split(".")
        module_name = parts[0]
        def_path = parts[1:]

        new_cls = reload_class(def_path, base_cls)
        if new_cls is not None:
            _CLASS_NOW[def_path_str] = new_cls

            # Wrap only new methods that aren't already wrapped
            for k, v in list(vars(new_cls).items()):
                if callable(v) and not isinstance(v, type(len)):
                    # Check if this method exists in the old class and is already wrapped
                    old_method = getattr(base_cls, k, None)
                    if old_method is None or not getattr(
                        old_method, _HOT_RESTART_ALREADY_WRAPPED, False
                    ):
                        _LOGGER.info(f"Wrapping new/updated method {new_cls!r}.{k}")
                        setattr(new_cls, k, wrap(v, _recursive=True))

            # Update the class in its module namespace
            module = sys.modules.get(module_name)
            if module and len(def_path) == 1:
                # Top-level class
                setattr(module, def_path[0], new_cls)
            elif module and len(def_path) > 1:
                # Nested class - navigate to parent
                parent = module
                for part in def_path[:-1]:
                    parent = getattr(parent, part, None)
                    if parent is None:
                        break
                if parent is not None:
                    setattr(parent, def_path[-1], new_cls)

            _LOGGER.debug(f"Reloaded class {def_path_str}")
        else:
            _LOGGER.warning(f"Failed to reload class {def_path_str}")


# Mapping from definition path strings to most up-to-date version of those functions
# External to wrap() so that it can be updated during full module reload.
_FUNC_NOW = {}

# Last version of a function from full module (re)load.
_FUNC_BASE = {}

# Mapping from definition path strings to most up-to-date version of those classes
_CLASS_NOW = {}

# Last version of a class from full module (re)load.
_CLASS_BASE = {}


def wrap(
    func=None,
    *,
    propagated_exceptions: tuple[type[Exception], ...] = (StopIteration,),
    propagate_keyboard_interrupt: bool = True,
    _recursive: bool = False,
):
    assert isinstance(propagated_exceptions, tuple), (
        "propagated_exceptions should be a tuple of exception types"
    )

    if func is None:
        return functools.partial(
            wrap,
            propagated_exceptions=propagated_exceptions,
            propagate_keyboard_interrupt=propagate_keyboard_interrupt,
            _recursive=_recursive,
        )

    if inspect.isclass(func):
        # Handle class wrapping directly
        return wrap_class(func)

    if _HOT_RESTART_IN_SURROGATE_CONTEXT.val:
        # We're in surrogate source, don't wrap again (or override the _FUNC_BASE)
        _HOT_RESTART_IN_SURROGATE_CONTEXT.val[_HOT_RESTART_SURROGATE_RESULT] = func
        return func

    if getattr(func, _HOT_RESTART_ALREADY_WRAPPED, False):
        _LOGGER.debug(f"Already wrapped {func!r}, not wrapping again")
        return func

    _LOGGER.debug(f"Wrapping {func!r}")

    try:
        _def_path = _get_def_path(func, _recursive=_recursive)
    except ReloadException as e:
        if not _recursive:
            _LOGGER.error(f"Could not wrap {func!r}: {e}")
        return func
    except (FileNotFoundError, OSError) as e:
        if not _recursive:
            _LOGGER.error(f"Could not wrap {func!r}: could not get source: {e}")
        return func

    if _def_path is None:
        error_msg = f"Could not get definition path for {func!r}"
        if not _recursive:
            _LOGGER.error(error_msg)
        raise ReloadException(error_msg)

    def_path = _def_path
    def_path_str = ".".join([func.__module__] + def_path)

    if inspect.unwrap(func) is not func:
        _LOGGER.warning(
            f"Wrapping {def_path_str}, but hot_restart.wrap is not innermost decorator."
        )
        _LOGGER.warning(f"Inner decorator {func!r} will be reloaded with function.")
        _LOGGER.warning(f"Closure values in {def_path_str} will be lost.")

    _LOGGER.debug(f"Adding new base {def_path_str}: {func!r}")
    _FUNC_BASE[def_path_str] = func
    _FUNC_NOW[def_path_str] = func

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        global PROGRAM_SHOULD_EXIT
        global _EXIT_THIS_FRAME
        _EXIT_THIS_FRAME = False
        restart_count = 0
        result = None
        while not PROGRAM_SHOULD_EXIT and not _EXIT_THIS_FRAME:
            if restart_count > 0:
                _LOGGER.info(f"Restarting {_FUNC_NOW[def_path_str]!r}")
            try:
                func_now = _FUNC_NOW[def_path_str]
                result = func_now(*args, **kwargs)
                return result
            except Exception as e:
                if isinstance(e, propagated_exceptions):
                    raise e

                if propagate_keyboard_interrupt and isinstance(e, KeyboardInterrupt):
                    # The user is probably intentionally exiting
                    PROGRAM_SHOULD_EXIT = True

                if not PROGRAM_SHOULD_EXIT and not _EXIT_THIS_FRAME:
                    excinfo = sys.exc_info()

                    new_tb, num_dead_frames = _create_undead_traceback(
                        excinfo[2], sys._getframe(1), wrapped
                    )
                    excinfo = (excinfo[0], excinfo[1], new_tb)

                    _start_post_mortem(def_path_str, excinfo, num_dead_frames)

                if PROGRAM_SHOULD_EXIT or _EXIT_THIS_FRAME:
                    _LOGGER.warning(f"Re-raising {e!r}")
                    _EXIT_THIS_FRAME = False
                    raise e
                elif RELOAD_ON_CONTINUE:
                    if RELOAD_ALL_ON_CONTINUE:
                        # Reload all wrapped functions and classes
                        reload_all_wrapped()
                        # The current function should have been reloaded as part of reload_all_wrapped
                        print("> Reloaded all wrapped functions and classes")
                    else:
                        # Just reload the current function
                        new_func = reload_function(def_path, _FUNC_BASE[def_path_str])
                        if new_func is not None:
                            print(f"> Reloaded {new_func!r}")
                            _FUNC_NOW[def_path_str] = new_func
            restart_count += 1
        return result

    setattr(wrapped, _HOT_RESTART_ALREADY_WRAPPED, True)

    return wrapped


def _create_undead_traceback(exc_tb, current_frame, wrapper_function):
    """Create a new traceback object that includes the current frame's parents."""

    # We want to default to one frame below the last one (the frame of the wrapper)
    num_dead_frames = -1
    dead_tb = exc_tb
    while dead_tb is not None and dead_tb.tb_next is not None:
        num_dead_frames += 1
        dead_tb = dead_tb.tb_next
    num_dead_frames = max(0, num_dead_frames)

    # If we would end up in the frame of the wrapper, jump up one more frame to
    # provide a more useful context
    if dead_tb is not None and dead_tb.tb_frame.f_code == wrapper_function.__code__:
        num_dead_frames += 1
        _LOGGER.warning("Debug frame is offset from restart frame")

    frame = current_frame

    # Create new traceback objects
    prev_tb = exc_tb
    while frame:
        if frame.f_code != wrapper_function.__code__:
            # Skip live wrapper frames to make the backtrace cleaner
            # Those calls are presumably not responsible for the crash, so
            # hiding them is fine.
            prev_tb = types.TracebackType(
                tb_next=prev_tb,
                tb_frame=frame,
                tb_lasti=frame.f_lasti,
                tb_lineno=frame.f_lineno,
            )
        frame = frame.f_back

    return prev_tb, num_dead_frames


def _start_post_mortem(def_path_str, excinfo, num_dead_frames):
    if DEBUGGER == "ipdb":
        _start_ipdb_post_mortem(def_path_str, excinfo, num_dead_frames)
    elif DEBUGGER == "pdb":
        _start_pdb_post_mortem(def_path_str, excinfo, num_dead_frames)
    elif DEBUGGER == "pydevd":
        _start_pydevd_post_mortem(def_path_str, excinfo)
    elif DEBUGGER == "pudb":
        _start_pudb_post_mortem(def_path_str, excinfo)
    else:
        _LOGGER.error(f"Unknown debugger {DEBUGGER}, falling back to breakpoint()")
        breakpoint()


def _start_ipdb_post_mortem(def_path_str, excinfo, num_dead_frames):
    global PRINT_HELP_MESSAGE
    global _EXIT_THIS_FRAME

    import ipdb  # noqa: F401
    from IPython.terminal.debugger import TerminalPdb

    class HotRestartIpdb(TerminalPdb):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        def _cmdloop(self) -> None:
            self.cmdloop()
            if PROGRAM_SHOULD_EXIT:
                TerminalPdb.set_quit(self)

        def set_quit(self):
            reraise()
            print(
                "Exitting debugging one level. Call hot_restart.exit() to exit the program."
            )
            super().set_quit()

    _, e, tb = excinfo
    # Print basic commands
    print(">")
    # e_msg = str(e)
    e_msg = repr(e)
    if not e_msg:
        e_msg = repr(e)
    print(f"> {def_path_str}: {e_msg}")
    if PRINT_HELP_MESSAGE:
        print(f"> (c)ontinue to revive {def_path_str}")
        PRINT_HELP_MESSAGE = False
    print(">")
    debugger = HotRestartIpdb()
    debugger.reset()

    debugger.cmdqueue.extend(["u"] * num_dead_frames)

    # Show source around exception
    debugger.cmdqueue.append("l")

    try:
        debugger.interaction(None, tb)
    except KeyboardInterrupt:
        # If user input KeyboardInterrupt from the debugger,
        # break up one level.
        _EXIT_THIS_FRAME = True


def _start_pudb_post_mortem(def_path_str, excinfo):
    e_type, e, tb = excinfo

    _LOGGER.debug(f"Entering pudb debugging of {def_path_str}")
    import pudb

    pudb.post_mortem(tb=tb, e_type=e_type, e_value=e)


def _start_pydevd_post_mortem(def_path_str, excinfo):
    print(f"hot-restart: Continue to revive {def_path_str}", file=sys.stderr)
    print(
        "hot-restart: call hot_restart.reraise() and continue to continue raising exception",
        file=sys.stderr,
    )
    try:
        import pydevd
    except ImportError:
        breakpoint()

    py_db = pydevd.get_global_debugger()
    if py_db is None:
        breakpoint()
    else:
        thread = threading.current_thread()
        additional_info = py_db.set_additional_thread_info(thread)
        additional_info.is_tracing += 1
        try:
            py_db.stop_on_unhandled_exception(py_db, thread, additional_info, excinfo)
        finally:
            additional_info.is_tracing -= 1


def _start_pdb_post_mortem(def_path_str, excinfo, num_dead_frames):
    global PRINT_HELP_MESSAGE
    global _EXIT_THIS_FRAME
    _, e, tb = excinfo
    # Print basic commands
    print(">")
    # e_msg = str(e)
    e_msg = repr(e)
    if not e_msg:
        e_msg = repr(e)
    print(f"> {def_path_str}: {e_msg}")
    if PRINT_HELP_MESSAGE:
        print(f"> (c)ontinue to revive {def_path_str}")
        PRINT_HELP_MESSAGE = False
    print(">")
    debugger = HotRestartPdb()
    debugger.reset()

    debugger.cmdqueue.extend(["u"] * num_dead_frames)

    # Show source around exception
    debugger.cmdqueue.append("l")

    try:
        debugger.interaction(None, tb)
    except KeyboardInterrupt:
        # If user input KeyboardInterrupt from the debugger,
        # break up one level.
        _EXIT_THIS_FRAME = True


def no_wrap(func_or_class):
    if func_or_class is None:
        return None
    setattr(func_or_class, _HOT_RESTART_NO_WRAP, True)
    return func_or_class


ignore = no_wrap


def wrap_class(cls):
    _LOGGER.debug(f"Wrapping class: {cls!r}")

    # Get definition path for the class
    try:
        def_path = _get_def_path(cls, _recursive=False)
        if def_path:
            def_path_str = ".".join([cls.__module__] + def_path)
            _LOGGER.debug(f"Registering class {def_path_str}")

            # Only register as base if not already registered
            if def_path_str not in _CLASS_BASE:
                _CLASS_BASE[def_path_str] = cls
            _CLASS_NOW[def_path_str] = cls
    except Exception as e:
        _LOGGER.warning(f"Could not get definition path for class {cls!r}: {e}")

    # Wrap all methods
    for k, v in list(vars(cls).items()):
        if callable(v) and not isinstance(v, type(len)):  # Skip built-in functions
            _LOGGER.debug(f"Wrapping {cls!r}.{k}")
            setattr(cls, k, wrap(v, _recursive=True))
    return cls


def is_restarting_module():
    return _IS_RESTARTING_MODULE.val


def wrap_module(module_or_name=None):
    if module_or_name is None:
        # Need to go get module of calling frame
        module_or_name = sys._getframe(1).f_globals["__name__"]
        module_name = module_or_name
    if isinstance(module_or_name, str):
        module_name = module_or_name
        module_d = sys.modules[module_or_name].__dict__
    else:
        module_name = module_or_name.__name__
        module_d = module_or_name.__dict__
    module_d = _HOT_RESTART_MODULE_RELOAD_CONTEXT.val.get(module_name, module_d)
    _LOGGER.debug(f"Wrapping module {module_name!r}")

    out_d = {}
    for k, v in list(module_d.items()):
        if getattr(v, _HOT_RESTART_NO_WRAP, False):
            _LOGGER.debug(f"Skipping wrapping of no_wrap {v!r}")
        elif getattr(v, _HOT_RESTART_ALREADY_WRAPPED, False):
            _LOGGER.debug(f"Skipping already wrapped {v!r}")
        elif inspect.isclass(v):
            v_module = inspect.getmodule(v)
            if v_module and v_module.__name__ == module_name:
                _LOGGER.debug(f"Wrapping class {v!r}")
                wrap_class(v)
            else:
                _LOGGER.debug(
                    f"Not wrapping in-scope class {v!r} since it originates from {v_module} != {module_name}"
                )
        elif callable(v) and not isinstance(v, type(len)):  # Skip built-in functions
            v_module = inspect.getmodule(v)
            if v_module and v_module.__name__ == module_name:
                _LOGGER.debug(f"Wrapping callable {v!r}")
                out_d[k] = wrap(v, _recursive=True)
            else:
                _LOGGER.debug(
                    f"Not wrapping in-scope callable {v!r} since it originates from {v_module} != {module_name}"
                )
        else:
            _LOGGER.debug(f"Not wrapping {v!r}")

    for k, v in out_d.items():
        module_d[k] = v


def wrap_modules(pattern):
    """
    Wrap multiple modules matching an fnmatch-style pattern.

    Args:
        pattern: An fnmatch-style pattern to match module names.
                Examples: '*' (all modules), 'myapp*' (modules starting with 'myapp'),
                         '*_utils' (modules ending with '_utils'), 'app.*.*' (nested modules)
    """
    import fnmatch

    _LOGGER.debug(f"Wrapping modules matching pattern: {pattern!r}")

    # Get all currently loaded modules
    modules_to_wrap = []
    for module_name, module in list(sys.modules.items()):
        if module is None:
            continue

        # Check if module name matches the pattern
        if fnmatch.fnmatch(module_name, pattern):
            # Skip built-in modules and modules without a file
            if hasattr(module, "__file__") and module.__file__:
                modules_to_wrap.append((module_name, module))

    _LOGGER.debug(f"Found {len(modules_to_wrap)} modules matching pattern {pattern!r}")

    # Wrap each matching module
    for module_name, module in modules_to_wrap:
        try:
            _LOGGER.debug(f"Wrapping module {module_name!r}")
            wrap_module(module)
        except Exception as e:
            _LOGGER.warning(f"Failed to wrap module {module_name!r}: {e}")


def restart_module(module_or_name=None):
    if module_or_name is None:
        # Need to go get module of calling frame
        module_or_name = sys._getframe(1).f_globals["__name__"]
        module_name = module_or_name
    if isinstance(module_or_name, str):
        module = sys.modules[module_or_name]
        module_name = module_or_name
    else:
        module = module_or_name
        module_name = module.__name__
    source_filename = inspect.getsourcefile(module)
    if source_filename is None:
        raise ReloadException(f"Could not determine source of {module!r}")
    try:
        with open(source_filename) as f:
            source = f.read()
    except (OSError, FileNotFoundError) as e:
        raise ReloadException(f"Could not load {module!r} source: {e!r}")

    _LOGGER.info(f"Reloading module {module!r} from source file {source_filename}")
    _LOGGER.debug("=== RELOAD SOURCE BEGIN ===")
    _LOGGER.debug(source)
    _LOGGER.debug("=== RELOAD SOURCE END ===")

    # Exec new source in copy of the context of the old module
    ctxt = dict(vars(module))
    code = compile(source, source_filename, "exec")

    try:
        _IS_RESTARTING_MODULE.val = True
        _HOT_RESTART_MODULE_RELOAD_CONTEXT.val[module_name] = ctxt
        exec(code, ctxt, ctxt)
    finally:
        _IS_RESTARTING_MODULE.val = False
        del _HOT_RESTART_MODULE_RELOAD_CONTEXT.val[module_name]

    for k, v in ctxt.items():
        setattr(module, k, v)


# Convenient alias
reload_module = restart_module

# Useful values for `from hot_restart import *`
__all__ = [
    "wrap",
    "no_wrap",
    "wrap_module",
    "wrap_modules",
    "wrap_class",
    "exit",
    "reraise",
    "ReloadException",
    "restart_module",
    "reload_module",
    "is_restarting_module",
]

# Also publicly available, but not useful to import via *
# DEBUGGER
# PROGRAM_SHOULD_EXIT
# PRINT_HELP_MESSAGE
# RELOAD_ON_CONTINUE
# RELOAD_ALL_ON_CONTINUE
