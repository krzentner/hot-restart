"""Restart debugging your program in the function that failed.

Basic usage:

import hot_restart; hot_restart.wrap_module()

See README.md for more detailed usage instructions.
"""

__version__ = "0.2.0"

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

old_except_hook = None

_LOGGER = logging.getLogger("hot-restart")
handler = logging.StreamHandler(sys.stderr)
formatter = logging.Formatter("%(levelname)s (%(name)s): %(message)s")
handler.setFormatter(formatter)
_LOGGER.addHandler(handler)
_LOGGER.setLevel(logging.WARN)

# Global configuration

## Automatically reload code on continue.
RELOAD_ON_CONTINUE = True

## Print the help message when first opening pdb
PRINT_HELP_MESSAGE = True

## Causes program to exit.
PROGRAM_SHOULD_EXIT = False

## Debugger to use
if "pydevd" in sys.modules:
    # Handles VSCode, probably others
    DEBUGGER = "pydevd"
    # Fake the path of generated sources to match the original source
    DEBUG_ORIGINAL_PATH_FOR_RELOADED_CODE = True
else:
    # Default stdlib wrapper
    DEBUGGER = "pdb"
    # Show the generated "surrogate" source in the debugger
    DEBUG_ORIGINAL_PATH_FOR_RELOADED_CODE = False

# Magic attribute names added by decorators
HOT_RESTART_ALREADY_WRAPPED = "_hot_restart_already_wrapped"
HOT_RESTART_NO_WRAP = "_hot_restart_no_wrap"

# Thread locals used during reload
HOT_RESTART_MODULE_RELOAD_CONTEXT = threading.local()
HOT_RESTART_MODULE_RELOAD_CONTEXT.val = {}

HOT_RESTART_SURROGATE_RESULT = "HOT_RESTART_SURROGATE_RESULT"

HOT_RESTART_IN_SURROGATE_CONTEXT = threading.local()
HOT_RESTART_IN_SURROGATE_CONTEXT.val = None

IS_RESTARTING_MODULE = threading.local()
IS_RESTARTING_MODULE.val = False

# This needs to be settable from the debugger UI
# Unfortunately we have no idea what thread the debugger will set this from
EXIT_THIS_FRAME = None


class HotRestartPdb(pdb.Pdb):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This flag is used to recursively exit the whole program, instead of
        # just exiting one post-mortem session.
        self.program_should_exit = False

    def _cmdloop(self) -> None:
        # The only difference vs normal Pdb is that this function does not
        # catch KeyboardInterrupt. This allows Ctrl-C to "jump up one level of
        # the stack", instead of clearing the current line.
        self.allow_kbdint = True
        self.cmdloop()
        self.allow_kbdint = False

    def set_quit(self):
        super().set_quit()
        self.program_should_exit = True


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
    global EXIT_THIS_FRAME
    EXIT_THIS_FRAME = True


# Mapping from definition paths to temp files of reloaded code.
# Temp files are allocated to hold surrogate source so that the debugger can
# still show correct code listings even after the files are updated.
# One source file is allocated per function.
TMP_SOURCE_FILES = {}


class ReloadException(ValueError):
    """Exception when hot-restart fails to reload a function."""

    pass


SUPER_REWRITE_RE = re.compile(r"super\((\s*)\)")


def rewrite_super_closures(src):
    return SUPER_REWRITE_RE.sub(r"super(type(self), self\1)", src)


class FindDefPath(ast.NodeVisitor):
    """Given a target name and line number of a definition, find a definition path.

    This gives a more durable identity to a function than its original line number.
    """

    def __init__(self, target_name: str, target_lineno: int):
        super().__init__()
        self.target_name = target_name
        self.target_lineno = target_lineno
        self.found_def_paths = []
        self.path_now = []

    def generic_visit(self, node: ast.AST) -> Any:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.path_now.append(node)
            start_lineno = min(
                [node.lineno] + [dec.lineno for dec in node.decorator_list]
            )
            end_lineno = getattr(node, "end_lineno", 0)
            if node.name == self.target_name:
                if (
                    start_lineno <= self.target_lineno
                    and self.target_lineno <= end_lineno
                ):
                    self.found_def_paths.append([node.name for node in self.path_now])
                else:
                    _LOGGER.debug("Found matching name to def at wrong lineno:")
                    _LOGGER.debug(f"    target_lineno = {self.target_lineno}")
                    _LOGGER.debug(f"    start_lineno = {start_lineno}")
                    _LOGGER.debug(f"    end_lineno = {end_lineno}")
            res = super().generic_visit(node)
            self.path_now.pop()
            return res
        else:
            return super().generic_visit(node)


class SurrogateTransformer:
    """Transforms module source ast into a module only containing a target
    function and any surrounding scopes necessary for the compile to build the
    right closure for that target.
    This module is compiled and executed in the context of the original module,
    preventing side effects.

    This is necessary for super() to work, since it implicitly is a closure
    over __class__.
    """

    def __init__(self, target_path: list[str], free_vars: list[str]):
        self.target_path = target_path
        self.depth = 0
        self.target_nodes = []
        self.original_lineno = 0
        self.free_vars = free_vars

    def flatten_module(self, node: ast.Module) -> ast.Module:
        return ast.Module(
            body=self.visit_body(node.body), type_ignores=node.type_ignores
        )

    def visit_body(self, nodes: list[ast.AST]) -> list[ast.AST]:
        new_nodes = []
        for n in nodes:
            new_nodes.extend(self.flatten_visit(n))
        return new_nodes

    def flatten_visit(self, node: ast.AST) -> list[ast.AST]:
        if isinstance(node, ast.ClassDef):
            if node.name != self.target_path[self.depth]:
                return []
            try:
                self.depth += 1
                return [
                    ast.ClassDef(
                        name=node.name,
                        bases=[],
                        keywords=node.keywords,
                        body=self.visit_body(node.body),
                        decorator_list=[],
                    )
                ]
            finally:
                self.depth -= 1
        elif isinstance(node, ast.FunctionDef):
            if node.name != self.target_path[self.depth]:
                return []
            try:
                self.depth += 1
                if self.depth == len(self.target_path):
                    self.original_lineno = node.lineno
                    # Found the function def
                    self.target_nodes.append(
                        ast.FunctionDef(
                            name=node.name,
                            args=node.args,
                            body=node.body,
                            decorator_list=node.decorator_list,
                            returns=node.returns,
                        )
                    )
                    freevar_bindings = ast.parse(
                        "\n".join(
                            f"{var} = 'HOT_RESTART_LOST_CLOSURE'"
                            for var in self.free_vars
                        )
                    ).body
                    res = (
                        freevar_bindings
                        + [
                            self.target_nodes[-1]
                            # If the original function was explicitly wrapped, the
                            # wrapper will set HOT_RESTART_SURROGATE_RESULT,
                            # otherwise generate some code here to set it.
                        ]
                        + ast.parse(
                            f"globals().setdefault('HOT_RESTART_SURROGATE_RESULT', {node.name})"
                        ).body
                    )
                    return res
                else:
                    # This is not the leaf function.
                    # Transform this function into a stub function that
                    # just creates the inner function.

                    # TODO: Create local variables to match original
                    # function so that closure bindings are created
                    # correctly

                    new_body = self.visit_body(node.body)
                    new_body.append(
                        ast.Return(
                            value=ast.Name(self.target_path[self.depth], ctx=ast.Load())
                        )
                    )
                    res = [
                        ast.FunctionDef(
                            name=node.name,
                            args=[],
                            body=new_body,
                            decorator_list=[],
                            returns=node.returns,
                        ),
                        # Immediately call the function, so the inner closure gets created
                    ] + ast.parse(f"{node.name}()").body
                    return res
            finally:
                self.depth -= 1
        elif hasattr(node, "body") or hasattr(node, "orelse"):
            return self.visit_body(
                getattr(node, "body", []) + getattr(node, "orelse", [])
            )
        else:
            return []


def build_surrogate_source(source_text, module_ast, def_path, free_vars):
    """Builds a source file containing the definition of def_path at the same
    lineno as in the ast, with the same parent class(es), but with all other
    lines empty.
    """
    trans = SurrogateTransformer(target_path=def_path, free_vars=free_vars)
    new_ast = ast.fix_missing_locations(trans.flatten_module(module_ast))
    source = ast.unparse(new_ast)
    target_nodes = trans.target_nodes
    def_path_str = ".".join(def_path)
    if len(target_nodes) == 0:
        _LOGGER.debug("=== BEGIN SOURCE TEXT ===")
        _LOGGER.debug(source_text)
        _LOGGER.debug("=== END SOURCE TEXT ===")
        _LOGGER.debug(ast.dump(new_ast, indent=2))
        raise ReloadException(f"Could not find {def_path_str} in new source")
    if len(target_nodes) > 1:
        _LOGGER.error(f"Overlapping definitions of {def_path_str} in source")
    target_node = target_nodes[0]
    missing_lines = trans.original_lineno - target_node.lineno
    surrogate_src = "\n" * missing_lines + source
    surrogate_src = rewrite_super_closures(surrogate_src)
    return surrogate_src


@functools.cache
def parse_src(source: str) -> ast.AST:
    return ast.parse(source)


def get_def_path(func) -> Optional[list[str]]:
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
    if source_filename == "<string>":
        raise ReloadException(f"{func!r} was generated and has no source")
    with open(source_filename, "r") as f:
        source_content = f.read()
    module_ast = parse_src(source_content)
    func_name = unwrapped_func.__name__
    func_lineno = unwrapped_func.__code__.co_firstlineno
    visitor = FindDefPath(target_name=func_name, target_lineno=func_lineno)
    visitor.visit(module_ast)
    if len(visitor.found_def_paths) == 0:
        _LOGGER.error(f"Could not find definition of {unwrapped_func!r}")
        _LOGGER.debug(ast.dump(module_ast, indent=2))
        return None
    def_path = visitor.found_def_paths[0]
    # Check that we can build a surrogate source for this func
    build_surrogate_source(
        source_content, module_ast, def_path, unwrapped_func.__code__.co_freevars
    )
    return visitor.found_def_paths[0]


def reload_function(def_path: list[str], func):
    """Takes in a definition path and function, and returns a new version of
    that function reloaded from source.

    This _does not_ cause the function to be reloaded in place (that's
    significantly more difficult to do, especially in a thread safe way).
    """

    def_str = ".".join(def_path)
    unwrapped_func = inspect.unwrap(func)
    source_filename = inspect.getsourcefile(unwrapped_func)
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
    surrogate_src = build_surrogate_source(
        all_source, src_ast, def_path, unwrapped_func.__code__.co_freevars
    )

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
    if DEBUG_ORIGINAL_PATH_FOR_RELOADED_CODE:
        _LOGGER.warn(f"Faking path of generated source for {func!r}")
        _LOGGER.warn(f"Real generated code source is in {temp_source.name}")
        surrogate_filename = source_filename
    code = compile(surrogate_src, surrogate_filename, "exec")
    ctxt = dict(vars(module))

    if HOT_RESTART_SURROGATE_RESULT in ctxt:
        del ctxt[HOT_RESTART_SURROGATE_RESULT]
        _LOGGER.error("Leftover result from surrogate load")

    try:
        HOT_RESTART_IN_SURROGATE_CONTEXT.val = ctxt
        exec(code, ctxt, ctxt)
    finally:
        HOT_RESTART_IN_SURROGATE_CONTEXT.val = None
    raw_func = ctxt.get(HOT_RESTART_SURROGATE_RESULT, None)
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
    TMP_SOURCE_FILES[def_str] = temp_source
    return new_func


# Mapping from definition path strings to most up-to-date version of those functions
# External to wrap() so that it can be updated during full module reload.
FUNC_NOW = {}

# Last version of a function from full module (re)load.
FUNC_BASE = {}


def wrap(
    func=None,
    *,
    propagated_exceptions: tuple[type[Exception], ...] = (),
    propagate_keyboard_interrupt: bool = True,
):
    if inspect.isclass(func):
        raise ValueError("Use hot_restart.wrap_class to wrap a class")

    assert isinstance(
        propagated_exceptions, tuple
    ), "propagated_exceptions should be a tuple of exception types"

    if func is None:
        return functools.partial(
            wrap,
            propagated_exceptions=propagated_exceptions,
            propagate_keyboard_interrupt=propagate_keyboard_interrupt,
        )

    if HOT_RESTART_IN_SURROGATE_CONTEXT.val:
        # We're in surrogate source, don't wrap again (or override the FUNC_BASE
        HOT_RESTART_IN_SURROGATE_CONTEXT.val[HOT_RESTART_SURROGATE_RESULT] = func
        return func

    if getattr(func, HOT_RESTART_ALREADY_WRAPPED, False):
        _LOGGER.debug(f"Already wrapped {func!r}, not wrapping again")
        return func

    _LOGGER.debug(f"Wrapping {func!r}")

    try:
        _def_path = get_def_path(func)
    except ReloadException as e:
        _LOGGER.error(f"Could not wrap {func!r}: {e}")
        return func
    except (FileNotFoundError, OSError) as e:
        _LOGGER.error(f"Could not wrap {func!r}: could not get source: {e}")
        return func

    if _def_path is None:
        _LOGGER.error(f"Could not get definition path for {func!r}")
        # Assume it's the trivial path
        def_path = [func.__name__]
    else:
        def_path = _def_path
    def_path_str = ".".join([func.__module__] + def_path)

    if inspect.unwrap(func) is not func:
        _LOGGER.warn(
            f"Wrapping {def_path_str}, but hot_restart.wrap is not innermost decorator."
        )
        _LOGGER.warn(f"Inner decorator {func!r} will be reloaded with function.")
        _LOGGER.warn(f"Closure values in {def_path_str} will be lost.")

    _LOGGER.debug(f"Adding new base {def_path_str}: {func!r}")
    FUNC_BASE[def_path_str] = func
    FUNC_NOW[def_path_str] = func

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        global PROGRAM_SHOULD_EXIT
        global EXIT_THIS_FRAME
        EXIT_THIS_FRAME = False
        restart_count = 0
        while not PROGRAM_SHOULD_EXIT and not EXIT_THIS_FRAME:
            if restart_count > 0:
                _LOGGER.info(f"Restarting {FUNC_NOW[def_path_str]!r}")
            try:
                func_now = FUNC_NOW[def_path_str]
                result = func_now(*args, **kwargs)
                return result
            except Exception as e:
                if isinstance(e, propagated_exceptions):
                    raise e

                if propagate_keyboard_interrupt and isinstance(e, KeyboardInterrupt):
                    # The user is probably intentionally exiting
                    PROGRAM_SHOULD_EXIT = True

                if not PROGRAM_SHOULD_EXIT and not EXIT_THIS_FRAME:
                    _start_post_mortem(def_path_str, sys.exc_info())

                if PROGRAM_SHOULD_EXIT or EXIT_THIS_FRAME:
                    _LOGGER.warn(f"Re-raising {e!r}")
                    raise e
                elif RELOAD_ON_CONTINUE:
                    new_func = reload_function(def_path, FUNC_BASE[def_path_str])
                    if new_func is not None:
                        print(f"> Reloaded {new_func!r}")
                        FUNC_NOW[def_path_str] = new_func
            restart_count += 1

    setattr(wrapped, HOT_RESTART_ALREADY_WRAPPED, True)

    return wrapped


def _start_post_mortem(def_path_str, excinfo):
    if DEBUGGER == "pdb":
        _start_pdb_post_mortem(def_path_str, excinfo)
    elif DEBUGGER == "pydevd":
        _start_pydevd_post_mortem(def_path_str, excinfo)
    else:
        _LOGGER.error(f"Unknown debugger {DEBUGGER}, falling back to breakpoint()")
        breakpoint()


def _start_pydevd_post_mortem(def_path_str, excinfo):
    print(f"hot-restart: Continue to revive {def_path_str}", file=sys.stderr)
    print(
        f"hot-restart: call hot_restart.reraise() and continue to continue raising exception",
        file=sys.stderr,
    )
    try:
        import pydevd
    except ImportError:
        breakpoint()

    py_db = pydevd.get_global_debugger()
    if py_db is None:
        breakpoint()
    thread = threading.current_thread()
    additional_info = py_db.set_additional_thread_info(thread)
    additional_info.is_tracing += 1
    try:
        py_db.stop_on_unhandled_exception(py_db, thread, additional_info, excinfo)
    finally:
        additional_info.is_tracing -= 1


def _start_pdb_post_mortem(def_path_str, excinfo):
    global PRINT_HELP_MESSAGE
    global EXIT_THIS_FRAME
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
        print("> Ctrl-C to re-raise exception")
        print("> (q)uit to exit program")
        PRINT_HELP_MESSAGE = False
    print(">")
    debugger = HotRestartPdb()
    debugger.reset()

    # Adjust starting frame of debugger to point at wrapped
    # function (just below wrapper frame).
    height = 0
    tb_next = tb.tb_next
    while tb_next.tb_next is not None:
        height += 1
        tb_next = tb_next.tb_next

    debugger.cmdqueue.extend(["u"] * height)

    # Show function source
    # TODO(krzentner): Use original source, instead of
    # re-fetching from file (which may be out of date)
    debugger.cmdqueue.append("ll")

    try:
        debugger.interaction(None, tb)
    except KeyboardInterrupt:
        # If user input KeyboardInterrupt from the debugger,
        # break up one level.
        EXIT_THIS_FRAME = True


def no_wrap(func_or_class):
    setattr(func_or_class, HOT_RESTART_NO_WRAP, True)
    return func_or_class


def wrap_class(cls):
    _LOGGER.info(f"Wrapping class: {cls!r}")
    for k, v in list(vars(cls).items()):
        if callable(v):
            _LOGGER.info(f"Wrapping {cls!r}.{k}")
            setattr(cls, k, wrap(v))


def is_restarting_module():
    return IS_RESTARTING_MODULE.val


def wrap_module(module_or_name=None):
    if module_or_name is None:
        # Need to go get module of calling frame
        module_or_name = inspect.currentframe().f_back.f_globals["__name__"]
        module_name = module_or_name
    if isinstance(module_or_name, str):
        module_name = module_or_name
        module_d = sys.modules[module_or_name].__dict__
    else:
        module_name = module_or_name.__name__
        module_d = module_or_name.__dict__
    module_d = HOT_RESTART_MODULE_RELOAD_CONTEXT.val.get(module_name, module_d)
    _LOGGER.info(f"Wrapping module {module_name!r}")

    out_d = {}
    for k, v in module_d.items():
        if getattr(v, HOT_RESTART_NO_WRAP, False):
            _LOGGER.info(f"Skipping wrapping of no_wrap {v!r}")
        elif getattr(v, HOT_RESTART_ALREADY_WRAPPED, False):
            _LOGGER.info(f"Skipping already wrapped {v!r}")
        elif inspect.isclass(v):
            v_module = inspect.getmodule(v)
            if v_module and v_module.__name__ == module_name:
                _LOGGER.info(f"Wrapping class {v!r}")
                wrap_class(v)
            else:
                _LOGGER.info(
                    f"Not wrapping in-scope class {v!r} since it originates from {v_module} != {module_name}"
                )
        elif callable(v):
            v_module = inspect.getmodule(v)
            if v_module and v_module.__name__ == module_name:
                _LOGGER.info(f"Wrapping callable {v!r}")
                out_d[k] = wrap(v)
            else:
                _LOGGER.info(
                    f"Not wrapping in-scope callable {v!r} since it originates from {v_module} != {module_name}"
                )
        else:
            _LOGGER.debug(f"Not wrapping {v!r}")

    for k, v in out_d.items():
        module_d[k] = v


def restart_module(module_or_name=None):
    if module_or_name is None:
        # Need to go get module of calling frame
        module_or_name = inspect.currentframe().f_back.f_globals["__name__"]
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

    # Rewrite super() -> super(type(self), self)
    # This fixes more problems than it causes.
    # If you need to avoid it, just use the two argument form of super() manually
    source = rewrite_super_closures(source)

    _LOGGER.info(f"Reloading module {module!r} from source file {source_filename}")
    _LOGGER.debug("=== RELOAD SOURCE BEGIN ===")
    _LOGGER.debug(source)
    _LOGGER.debug("=== RELOAD SOURCE END ===")

    # Exec new source in copy of the context of the old module
    ctxt = dict(vars(module))
    code = compile(source, source_filename, "exec")

    try:
        IS_RESTARTING_MODULE.val = True
        HOT_RESTART_MODULE_RELOAD_CONTEXT.val[module_name] = ctxt
        exec(code, ctxt, ctxt)
    finally:
        IS_RESTARTING_MODULE.val = False
        del HOT_RESTART_MODULE_RELOAD_CONTEXT.val[module_name]

    for k, v in ctxt.items():
        setattr(module, k, v)


# Convenient alias
reload_module = restart_module


__all__ = [
    "wrap",
    "no_wrap",
    "wrap_module",
    "wrap_class",
    "exit",
    "reraise",
    "PROGRAM_SHOULD_EXIT",
    "PRINT_HELP_MESSAGE",
    "ReloadException",
    "restart_module",
    "reload_module",
    "is_restarting_module",
    "RELOAD_ON_CONTINUE",
]
