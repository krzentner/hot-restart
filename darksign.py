import sys
import queue
import logging
import functools
import threading
import pdb
import inspect
import tokenize
# from importlib import util
# import importlib.machinery
import tempfile

old_except_hook = None

_LOGGER = logging.getLogger('darksign')
_LOGGER.addHandler(logging.StreamHandler(sys.stderr))
_LOGGER.setLevel(logging.DEBUG)

_to_watcher = queue.Queue()


class DarksignPdb(pdb.Pdb):

    def _cmdloop(self) -> None:
        # The only difference vs normal Pdb is that this function does not
        # catch KeyboardInterrupt. Without this, exiting a darksign program can
        # be difficult, since inputting q just leads to the function
        # restarting.
        self.allow_kbdint = True
        self.cmdloop()
        self.allow_kbdint = False


PROGRAM_SHOULD_EXIT = False

def exit():
    global PROGRAM_SHOULD_EXIT
    PROGRAM_SHOULD_EXIT = True

# Mapping from original filenames to temp files
TMP_SOURCE_FILES = {}


def reload_function(func):
    try:
        module = inspect.getmodule(func)
        source_filename = inspect.getsourcefile(func)
        if source_filename is None:
            # Probably used in an interactive session or something, which
            # doesn't work :/
            _LOGGER.error(f"Could not reload {func!r}: No known source file")
            return None
        source_lines, start_linenum = inspect.getsourcelines(func)
        temp_source = tempfile.TemporaryFile(suffix='.py', mode='w')
        contents = (['\n'] * (start_linenum - 1)) + source_lines
        temp_source.writelines(contents)
        file_content = ''.join(contents)
        code = compile(file_content, source_filename, 'exec')
        loc = {}
        exec(code, vars(module), loc)
        new_func = loc.get(func.__name__, None)
        if new_func is not None:
            TMP_SOURCE_FILES[source_filename] = temp_source
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


SHOULD_HOT_RELOAD = True
WATCHER_THREAD = None


def wrap(original_func):
    global WATCHER_THREAD
    if WATCHER_THREAD is None and SHOULD_HOT_RELOAD:
        WATCHER_THREAD = threading.Thread(target=watcher_main, daemon=True)
        WATCHER_THREAD.start()
    func_now = original_func
    @functools.wraps(original_func)
    def darksign_wrapper(*args, **kwargs):
        nonlocal func_now
        global PROGRAM_SHOULD_EXIT
        restart_count = 0
        while not PROGRAM_SHOULD_EXIT:
            if restart_count > 0:
                _LOGGER.debug(f"Restarting {func_now!r}")
            try:
                result = func_now(*args, **kwargs)
                return result
            except Exception as e:
                if isinstance(e, KeyboardInterrupt):
                    # The user is probably intentionally exiting
                    PROGRAM_SHOULD_EXIT = True

                if not PROGRAM_SHOULD_EXIT:
                    traceback = sys.exc_info()[2]
                    debugger = DarksignPdb()
                    debugger.reset()
                    _to_watcher.put(('tb',
                                     (threading.get_ident(),
                                      traceback,
                                      debugger)))
                    try:
                        debugger.interaction(None, traceback)
                    except KeyboardInterrupt:
                        # If user input KeyboardInterrupt from the debugger,
                        # exit the program.
                        PROGRAM_SHOULD_EXIT = True
                    new_func = reload_function(original_func)
                    if new_func is not None:
                        func_now = new_func

                if PROGRAM_SHOULD_EXIT:
                    raise e
            restart_count += 1
    return darksign_wrapper
