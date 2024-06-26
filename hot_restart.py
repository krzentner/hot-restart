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
import weakref
import re

old_except_hook = None

_LOGGER = logging.getLogger("hot-restart")
handler = logging.StreamHandler(sys.stderr)
formatter = logging.Formatter('%(levelname)s (%(name)s): %(message)s')
handler.setFormatter(formatter)
_LOGGER.addHandler(handler)
_LOGGER.setLevel(logging.WARN)


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


PROGRAM_SHOULD_EXIT = False


def exit():
    """It can sometimes be hard to exit hot_restart programs.
    Calling this function (and exiting any debugger sessions) will
    short-circuit any hot_restart wrappers.
    """
    global PROGRAM_SHOULD_EXIT
    PROGRAM_SHOULD_EXIT = True


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
            start_lineno = min([node.lineno] + [dec.lineno for dec in node.decorator_list])
            end_lineno = getattr(node, 'end_lineno', 0)
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

    def __init__(self, target_path: list[str]):
        self.target_path = target_path
        self.depth = 0
        self.target_nodes = []
        self.original_lineno = 0

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
                    self.target_nodes.append(ast.FunctionDef(
                        name=node.name,
                        args=node.args,
                        body=node.body,
                        decorator_list=node.decorator_list,
                        returns=node.returns,
                    ))
                    res = [
                        self.target_nodes[-1]
                        # If the original function was explicitly wrapped, the
                        # wrapper will set HOT_RESTART_SURROGATE_RESULT,
                        # otherwise generate some code here to set it.
                    ] + ast.parse(f"globals().setdefault('HOT_RESTART_SURROGATE_RESULT', {node.name})").body
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


def build_surrogate_source(module_ast, def_path):
    """Builds a source file containing the definition of def_path at the same
    lineno as in the ast, with the same parent class(es), but with all other
    lines empty.
    """
    trans = SurrogateTransformer(target_path=def_path)
    new_ast = ast.fix_missing_locations(trans.flatten_module(module_ast))
    # _LOGGER.debug(ast.dump(new_ast, indent=2))
    source = ast.unparse(new_ast)
    target_nodes = trans.target_nodes
    def_path_str = '.'.join(def_path)
    if len(target_nodes) == 0:
        raise ReloadException(f"Could not find {def_path_str} in new source")
    if len(target_nodes) > 1:
        _LOGGER.error(f"Overlapping definitions of {def_path_str} in source")
    target_node = target_nodes[0]
    missing_lines = trans.original_lineno - target_node.lineno
    surrogate_src = "\n" * missing_lines + source
    surrogate_src = rewrite_super_closures(surrogate_src)
    return surrogate_src

HOT_RESTART_SURROGATE_RESULT = "HOT_RESTART_SURROGATE_RESULT"
HOT_RESTART_IN_SURROGATE_CONTEXT = threading.local()
HOT_RESTART_IN_SURROGATE_CONTEXT.val = None

ORIGINAL_SOURCE_CACHE = {}
ORIGINAL_SOURCE_AST_CACHE = {}


def get_def_path(func) -> Optional[list[str]]:

    unwrapped_func = inspect.unwrap(func)
    if unwrapped_func is not func:
        _LOGGER.debug("Finding def path of wrapped function.")
        try:
            _LOGGER.debug(f"function {func!r} has source file {inspect.getsourcefile(func)}")
        except TypeError:
            _LOGGER.debug(f"function {func!r} has no source file")

        _LOGGER.debug(f"unwrapped function {unwrapped_func!r} has source file {inspect.getsourcefile(unwrapped_func)}")

    source_filename = inspect.getsourcefile(unwrapped_func)
    if source_filename not in ORIGINAL_SOURCE_AST_CACHE:
        with open(source_filename, "r") as f:
            content = f.read()
            ORIGINAL_SOURCE_CACHE[source_filename] = content
            ORIGINAL_SOURCE_AST_CACHE[source_filename] = ast.parse(content)
    module_ast = ORIGINAL_SOURCE_AST_CACHE[source_filename]
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
    build_surrogate_source(module_ast, def_path)
    return visitor.found_def_paths[0]


def reload_function(def_path: list[str], func):
    """Takes in a definition path and function, and returns a new version of
    that function reloaded from source.

    This _does not_ cause the function to be reloaded in place (that's
    significantly more difficult to do, especially in a thread safe way).
    """

    def_str = ".".join(def_path)
    source_filename = inspect.getsourcefile(inspect.unwrap(func))
    try:
        with open(source_filename, "r") as f:
            all_source = f.read()
    except (OSError, FileNotFoundError, tokenize.TokenError) as e:
        _LOGGER.error(f"Could not read source for {func!r}: {e!r}")
        return None
    try:
        src_ast = ast.parse(all_source, filename=source_filename)
    except SyntaxError as e:
        _LOGGER.error(f"Could not read source for {func!r}: {e!r}")
        return None

    module = inspect.getmodule(func)
    if source_filename is None:
        # Probably used in an interactive session or something, which
        # we don't know how to get source code from.
        _LOGGER.error(f"Could not reload {func!r}: No known source file")
        return None
    surrogate_src = build_surrogate_source(src_ast, def_path)

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

    code = compile(surrogate_src, temp_source.name, "exec")
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
        new_func = types.FunctionType(
            raw_func.__code__,
            func.__globals__,
            raw_func.__name__,
            raw_func.__defaults__,
            # TODO(krzentner): Match up cell names, instead of blindly copying __closure__
            func.__closure__,
        )
    else:
        # We already warn about this on wrap, no need to repeat on reload
        _LOGGER.debug("wrap was not innermost decorator of {def_str}, closures (e.g. super()) will not work")
        new_func = raw_func
    # Keep new temp file alive until function is reloaded again
    TMP_SOURCE_FILES[def_str] = temp_source
    return new_func


SHOULD_HOT_RESTART = True
PRINT_HELP_MESSAGE = True


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
        HOT_RESTART_IN_SURROGATE_CONTEXT.val[HOT_RESTART_SURROGATE_RESULT] = func

    if getattr(func, HOT_RESTART_ALREADY_WRAPPED, False):
        _LOGGER.debug(f"Already wrapped {func!r}, not wrapping again")
        return func

    if inspect.unwrap(func) is not func:
        _LOGGER.warn(f"Wrapping {func!r}, but hot_restart.wrap is not innermost decorator.")
        _LOGGER.warn(f"Inner decorator will be reloaded with function {func!r}.")
        _LOGGER.warn(f"Closures in {func!r} (e.g. super()) will not be patched.")

    _LOGGER.debug(f"Wrapping {func!r}")

    _def_path = get_def_path(func)
    if _def_path is None:
        _LOGGER.error(f"Could not get definition path for {func!r}")
        # Assume it's the trivial path
        def_path = [func.__name__]
    else:
        def_path = _def_path
    def_path_str = ".".join([func.__module__] + def_path)
    FUNC_BASE[def_path_str] = func
    FUNC_NOW[def_path_str] = func

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        global PROGRAM_SHOULD_EXIT
        global PRINT_HELP_MESSAGE
        should_exit_this_level = False
        restart_count = 0
        while not PROGRAM_SHOULD_EXIT and not should_exit_this_level:
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

                if not PROGRAM_SHOULD_EXIT and not should_exit_this_level:
                    traceback = sys.exc_info()[2]

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
                    # function (just below "this" frame).
                    height = 0
                    tb_next = traceback.tb_next
                    while tb_next.tb_next is not None:
                        height += 1
                        tb_next = tb_next.tb_next

                    debugger.cmdqueue.extend(["u"] * height)

                    # Show function source
                    # TODO(krzentner): Use original source, instead of
                    # re-fetching from file (which may be out of date)
                    debugger.cmdqueue.append("ll")

                    try:
                        debugger.interaction(None, traceback)
                    except KeyboardInterrupt:
                        # If user input KeyboardInterrupt from the debugger,
                        # break up one level.
                        should_exit_this_level = True
                    if debugger.program_should_exit:
                        PROGRAM_SHOULD_EXIT = True

                if PROGRAM_SHOULD_EXIT or should_exit_this_level:
                    raise e
                else:
                    new_func = reload_function(def_path, FUNC_BASE[def_path_str])
                    if new_func is not None:
                        print(f"> Reloaded {new_func!r}")
                        FUNC_NOW[def_path_str] = new_func
            restart_count += 1

    setattr(wrapped, HOT_RESTART_ALREADY_WRAPPED, True)

    return wrapped


HOT_RESTART_ALREADY_WRAPPED = "_hot_restart_already_wrapped"
HOT_RESTART_NO_WRAP = "_hot_restart_no_wrap"


def no_wrap(func_or_class):
    setattr(func_or_class, HOT_RESTART_NO_WRAP, True)
    return func_or_class


def wrap_class(cls):
    for k, v in inspect.getmembers(cls, predicate=inspect.isfunction):
        setattr(cls, k, wrap(v))


HOT_RESTART_MODULE_RELOAD_CONTEXT = threading.local()
HOT_RESTART_MODULE_RELOAD_CONTEXT.val = {}

IS_RESTARTING_MODULE = threading.local()
IS_RESTARTING_MODULE.val = False

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
        elif callable(k):
            _LOGGER.info(f"Wrapping callable {v!r}")
            out_d[k] = wrap(v)
        elif inspect.isclass(v):
            _LOGGER.info(f"Wrapping class {v!r}")
            wrap_class(v)
    for k, v in out_d.items():
        module_d[k] = v


MODULE_SOURCES = {}
CLASS_VERSIONS = {}


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

    ORIGINAL_SOURCE_CACHE[source_filename] = source
    ORIGINAL_SOURCE_AST_CACHE[source_filename] = ast.parse(source)

    _LOGGER.info(f"Reloading module {module!r} from source file {source_filename}")
    flat_filename = (
        source_filename.replace("/", "_").replace("\\", "_").replace(":", "_")
    )

    # Allocate a temporary source file to make debugger listings more accurate
    temp_source = tempfile.NamedTemporaryFile(suffix=flat_filename, mode="w")
    temp_source.write(source)
    temp_source.flush()

    _LOGGER.debug("=== RELOAD SOURCE BEGIN ===")
    _LOGGER.debug(source)
    _LOGGER.debug("=== RELOAD SOURCE END ===")

    # Exec new source in copy of the context of the old module
    ctxt = dict(vars(module))
    code = compile(source, temp_source.name, "exec")

    try:
        IS_RESTARTING_MODULE.val = True
        HOT_RESTART_MODULE_RELOAD_CONTEXT.val[module_name] = ctxt
        exec(code, ctxt, ctxt)
    finally:
        IS_RESTARTING_MODULE.val = False
        del HOT_RESTART_MODULE_RELOAD_CONTEXT.val[module_name]

    # Patch classes in original module so that old instances get new methods
    def patch_class(dst_cls, src_cls, path):
        print("patching", path)
        for src_k, src_v in inspect.getmembers(src_cls):
            if src_k.startswith('__'):
                # Likely magic, do not patch
                continue
            dst_v = getattr(dst_cls, src_k, None)
            if dst_v and inspect.isclass(dst_v) and inspect.isclass(src_v):
                patch_class(dst_v, src_v, path=f"{path}.{src_k}")
            print("setattr(", v, src_k, src_v, ")")
            setattr(v, src_k, src_v)

        # It's impossible to prevent some old versions of the class from being
        # around. Unforunately this makes each reload of a module take more
        # time (O(n^2) cost for n reloads), but we use weakref to only patch
        # classes that are still potentially in use.
        previous_class_versions = CLASS_VERSIONS.get(path, [])
        previous_class_versions = [r for r in previous_class_versions if r()]
        for prev_version in previous_class_versions:
            strong_ref = prev_version()
            if strong_ref is not None:
                for src_k, src_v in inspect.getmembers(src_cls):
                    setattr(strong_ref, src_k, src_v)
        previous_class_versions.append(weakref.ref(dst_cls))
        CLASS_VERSIONS[path] = previous_class_versions

    for k, v in ctxt.items():
        if inspect.isclass(v):
            dst_cls = getattr(module, k, None)
            if dst_cls and inspect.isclass(dst_cls):
                patch_class(dst_cls, v, path=module.__name__)
        # Still try to use the most recent version of each class
        # We're most likely using code with references to the newest version
        # Unforunately this might result in confusion when performing
        # isinstance checks across modules
        setattr(module, k, v)

    # Just keep all of the old source files around until the program exits
    # It's very difficult to tell if any functions from this source function
    # still exist somwhere
    MODULE_SOURCES.get(module.__name__, []).append(temp_source)

# Convenient alias
reload_module = restart_module


__all__ = [
    "wrap",
    "no_wrap",
    "wrap_module",
    "wrap_class",
    "exit",
    "PROGRAM_SHOULD_EXIT",
    "PRINT_HELP_MESSAGE",
    "ReloadException",
    "restart_module",
    "reload_module",
    "is_restarting_module",
]
