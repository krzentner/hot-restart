import sys
import queue
import logging
import functools
import threading
import pdb
import inspect
from token import OP
import tokenize
import tempfile
import ast
from typing import Any, Optional
import textwrap
import types

old_except_hook = None

_LOGGER = logging.getLogger('darksign')
_LOGGER.addHandler(logging.StreamHandler(sys.stderr))
_LOGGER.setLevel(logging.ERROR)

_to_watcher = queue.Queue()


class DarksignPdb(pdb.Pdb):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.program_should_exit = False

    def _cmdloop(self) -> None:
        # The only difference vs normal Pdb is that this function does not
        # catch KeyboardInterrupt. Without this, exiting a darksign program can
        # be difficult, since inputting q just leads to the function
        # restarting.
        self.allow_kbdint = True
        self.cmdloop()
        self.allow_kbdint = False

    def set_quit(self):
        super().set_quit()
        self.program_should_exit = True



PROGRAM_SHOULD_EXIT = False

def exit():
    global PROGRAM_SHOULD_EXIT
    PROGRAM_SHOULD_EXIT = True

# Mapping from original filenames to temp files
TMP_SOURCE_FILES = {}


class ReloadException(ValueError):
    pass


class FindDefPath(ast.NodeVisitor):
    def __init__(self, target_name: str, target_lineno: int):
        super().__init__()
        self.target_name = target_name
        self.target_lineno = target_lineno
        self.found_def_paths = []
        self.path_now = []

    def generic_visit(self, node: ast.AST) -> Any:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.path_now.append(node)
            if node.lineno == self.target_lineno and node.name == self.target_name:
                self.found_def_paths.append([node.name for node in self.path_now])
            res = super().generic_visit(node)
            self.path_now.pop()
            return res
        else:
            return super().generic_visit(node)


class GetDefFromePath(ast.NodeVisitor):
    def __init__(self, target_path: list[str]):
        super().__init__()
        self.target_path = target_path
        self.depth = 0
        self.found_defs = []

    def generic_visit(self, node: ast.AST) -> Any:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == self.target_path[self.depth]:
                self.depth += 1
                if self.depth == len(self.target_path):
                    self.found_defs.append(node)
                res = super().generic_visit(node)
                self.depth -= 1
                return res
        return super().generic_visit(node)


class SurrogateTransformer:

    def __init__(self, target_path: list[str]):
        self.target_path = target_path
        self.depth = 0
        self.target_node = None
        self.original_lineno = 0

    def flatten_module(self, node: ast.Module) -> ast.Module:
        return ast.Module(
                body=self.visit_body(node.body),
                type_ignores=node.type_ignores)

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
                return [ast.ClassDef(
                    name=node.name,
                    bases=[],
                    keywords=node.keywords,
                    body=self.visit_body(node.body),
                    decorator_list=[],
                )]
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
                    self.target_node = ast.FunctionDef(
                        name=node.name,
                        args=node.args,
                        body=node.body,
                        decorator_list=[],
                        returns=node.returns,
                    )
                    return [self.target_node]
                else:
                    # This is not the leaf function.
                    # Transform this function into a stub function that
                    # just creates an inner function and returns it.

                    # TODO: Create local variables to match original
                    # function so that closure bindings are created
                    # correctly

                    new_body = [self.generic_visit(n) for n in node.body]
                    new_body = [n for n in new_body if n]
                    new_body.append(ast.Return(
                        value=ast.Name(self.target_path[self.depth], ctx=ast.Load())
                    ))
                    return [ast.FunctionDef(
                        name=node.name,
                        args=[],
                        body=new_body,
                        decorator_list=[],
                        returns=node.returns,
                    )]
            finally:
                self.depth -= 1
        elif hasattr(node, 'body') or hasattr(node, 'orelse'):
            return self.visit_body(getattr(node, 'body', []) + getattr(node, 'orelse', []))
        else:
            return []


def build_surrogate_source(module_ast, def_path):
    """Builds a source file containing the definition of def_path at the same
    lineno as in the original source, with the same parent class(es), but with
    all other lines empty.
    """
    trans = SurrogateTransformer(target_path=def_path)
    new_ast = ast.fix_missing_locations(trans.flatten_module(module_ast))
    _LOGGER.debug(ast.dump(new_ast, indent=2))
    source = ast.unparse(new_ast)
    target_node = trans.target_node
    if target_node is None:
        raise ReloadException("Could not find {'.'.join(def_path)} in new source")
    missing_lines = (trans.original_lineno - target_node.lineno - 2)
    surrogate_src = '\n' * missing_lines + source
    return surrogate_src


ORIGINAL_SOURCE_CACHE = {}
ORIGINAL_SOURCE_AST_CACHE = {}


def get_def_path(func):
    source_filename = inspect.getsourcefile(func)
    if source_filename not in ORIGINAL_SOURCE_AST_CACHE:
        with open(source_filename, 'r') as f:
            content = f.read()
            ORIGINAL_SOURCE_CACHE[source_filename] = content
            ORIGINAL_SOURCE_AST_CACHE[source_filename] = ast.parse(content)
    module_ast = ORIGINAL_SOURCE_AST_CACHE[source_filename]
    func_name = func.__name__
    original_lines, func_lineno = inspect.getsourcelines(func)
    del original_lines
    visitor = FindDefPath(target_name=func_name, target_lineno=func_lineno + 1)
    visitor.visit(module_ast)
    if len(visitor.found_def_paths) == 0:
        _LOGGER.error(f"Could not find definition of {func!r}")
        return None
    def_path = visitor.found_def_paths[0]
    # Check that we can build a surrogate source for this func
    build_surrogate_source(module_ast, def_path)
    return visitor.found_def_paths[0]


def reload_function(def_path: list[str], func):
    try:
        source_filename = inspect.getsourcefile(func)
        with open(source_filename, 'r') as f:
            all_source = f.read()
        src_ast = ast.parse(all_source, filename=source_filename)

        module = inspect.getmodule(func)
        if source_filename is None:
            # Probably used in an interactive session or something, which
            # doesn't work :/
            _LOGGER.error(f"Could not reload {func!r}: No known source file")
            return None
        surrogate_src = build_surrogate_source(src_ast, def_path)

        flat_filename = (
            source_filename
                .replace('/', '_')
                .replace('\\', '_')
                .replace(':', '_')
        )
        temp_source = tempfile.NamedTemporaryFile(
            suffix=flat_filename, mode='w')
        temp_source.write(surrogate_src)
        temp_source.flush()
        # _LOGGER.debug("=== SURROGATE SOURCE ===")
        # _LOGGER.debug(surrogate_src)
        code = compile(surrogate_src, temp_source.name, 'exec')
        loc = {}
        exec(code, vars(module), loc)
        for var_name in def_path[:-1]:
            loc = vars(loc[var_name])
        raw_func = loc.get(func.__name__, None)
        if raw_func is None:
            raise ReloadException("Could not retrieve {'.'.join(def_path)}")
        new_func = types.FunctionType(
            raw_func.__code__,
            func.__globals__,
            func.__name__,
            raw_func.__defaults__,
            func.__closure__, # TODO: Match up cell names, instead of blindly copying __closure__
        )
        if new_func is not None:
            TMP_SOURCE_FILES[source_filename] = temp_source
        print(f"> Reloaded {'.'.join(def_path)}")
        return new_func
    except (OSError, SyntaxError, tokenize.TokenError) as e:
        _LOGGER.error(f"Could not reload {func!r}: {e}")
        return None


def watcher_main():
    while True:
        cmd, contents = _to_watcher.get(block=True)
        if cmd == 'tb':
            thread_id, traceback, debugger = contents
            # time.sleep(2.0)
            # print("Code was patched, interrupting debugger...")
            # ctype_async_raise(thread_id, CodePatched())
            # debugger = _get_debugger_from_tb(traceback)
            # print('debugger', debugger)
        elif cmd == 'watch':
            source_filename, original_obj = contents
        else:
            _LOGGER.error(f"Uknown watcher command: {cmd}")


SHOULD_HOT_RELOAD = True
WATCHER_THREAD = None
PRINT_HELP_MESSAGE = False


def wrap(original_func):
    global WATCHER_THREAD
    if WATCHER_THREAD is None and SHOULD_HOT_RELOAD:
        WATCHER_THREAD = threading.Thread(target=watcher_main, daemon=True)
        WATCHER_THREAD.start()
    def_path = get_def_path(original_func)
    source_filename = inspect.getsourcefile(original_func)
    # _to_watcher.put(('watch', (source_filename, original_func)))
    func_now = original_func
    @functools.wraps(original_func)
    def darksign_wrapper(*args, **kwargs):
        nonlocal func_now
        global PROGRAM_SHOULD_EXIT
        global PRINT_HELP_MESSAGE
        should_exit_this_level = False
        restart_count = 0
        while not PROGRAM_SHOULD_EXIT and not should_exit_this_level:
            if restart_count > 0:
                _LOGGER.debug(f"Restarting {func_now!r}")
            try:
                result = func_now(*args, **kwargs)
                return result
            except Exception as e:
                if isinstance(e, KeyboardInterrupt):
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
                    print(f"> {func_now.__name__}: {e_msg}")
                    if PRINT_HELP_MESSAGE:
                        print(f"> (c)ontinue to revive {func_now.__name__!r}")
                        print("> Ctrl-C to re-raise exception")
                        print("> (q)uit to exit program")
                        PRINT_HELP_MESSAGE = False
                    print(">")
                    debugger = DarksignPdb()
                    debugger.reset()

                    # Adjust starting frame of debugger
                    height = 0
                    tb_next = traceback.tb_next
                    while tb_next.tb_next is not None:
                        height += 1
                        tb_next = tb_next.tb_next

                    for _ in range(height):
                        debugger.cmdqueue.append('u')

                    # Show function source
                    # TODO(krzentner): Use original source, instead of
                    # re-fetching from file (which may be out of date)
                    debugger.cmdqueue.append('ll')
                    _to_watcher.put(('tb',
                                     (threading.get_ident(),
                                      traceback,
                                      debugger)))
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
                    new_func = reload_function(def_path, original_func)
                    if new_func is not None:
                        func_now = new_func
            restart_count += 1
    return darksign_wrapper
