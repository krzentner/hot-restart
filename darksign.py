import sys
import queue
import logging
import functools
import threading
import pdb
import inspect
import tokenize
import tempfile
import ast
from typing import Any
import textwrap
import types

old_except_hook = None

_LOGGER = logging.getLogger('darksign')
_LOGGER.addHandler(logging.StreamHandler(sys.stderr))
_LOGGER.setLevel(logging.DEBUG)

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


def get_sourcelines(module_source, module_ast, def_path):
    visitor = GetDefFromePath(target_path=def_path)
    visitor.visit(module_ast)
    try:
        definition = visitor.found_defs[0]
    except IndexError:
        raise ReloadException(f"Could not find defintion for {'.'.join(def_path)}")
    src_segment = ast.get_source_segment(module_source, definition, padded=True)
    if src_segment is None:
        raise ReloadException(f"Definition of {'.'.join(def_path)} does not have a source segment")
    src_segment = textwrap.dedent(src_segment)
    return src_segment, definition.lineno


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
    src_segment, lineno = get_sourcelines(
            ORIGINAL_SOURCE_CACHE[source_filename], module_ast, def_path)
    del lineno
    return visitor.found_def_paths[0]


def reload_function(def_path, func):
    # print(dir(func))
    # print(func.__closure__)
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
        # source_lines, start_linenum = inspect.getsourcelines(func)

        source_lines, start_linenum = get_sourcelines(
            all_source, src_ast, def_path)

        matched_lineno_src = ('\n' * (start_linenum - 1)) + source_lines

        temp_source = tempfile.TemporaryFile(suffix='.py', mode='w')
        temp_source.write(matched_lineno_src)
        print('=== Reloading ===')
        print(matched_lineno_src)
        code = compile(matched_lineno_src, source_filename, 'exec')
        context = module
        for var_name in def_path[:-1]:
            context = getattr(context, var_name)
        loc = dict(vars(context))
        print('Executing with context:', context)
        exec(code, vars(module), loc)
        raw_func = loc.get(func.__name__, None)
        # new_func = types.FunctionType(
        #     raw_func.__code__,
        #     func.__globals__,
        #     func.__name__,
        #     raw_func.__defaults__,
        #     func.__closure__, # TODO: Match up cell names, instead of blindly copying __closure__
        # )
        print('=== Done Reloading ===')
        if new_func is not None:
            TMP_SOURCE_FILES[source_filename] = temp_source
        print(f"Reloaded {func.__name__!r}")
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
                    print()
                    # e_msg = str(e)
                    e_msg = repr(e)
                    if not e_msg:
                        e_msg = repr(e)
                    print(f"{func_now.__name__}: {e_msg}")
                    if PRINT_HELP_MESSAGE:
                        print(f"(c)ontinue to revive {func_now.__name__!r}")
                        print("Ctrl-C to re-raise exception")
                        print("(q)uit to exit program")
                        PRINT_HELP_MESSAGE = False
                    print()
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
