import ctypes
import sys
import queue
import logging
import time
import functools
import threading
import pdb

old_except_hook = None

_LOGGER = logging.getLogger('darksign')
_LOGGER.addHandler(logging.StreamHandler(sys.stderr))
_LOGGER.setLevel(logging.DEBUG)

_to_watcher = queue.Queue()


class DarksignPdb(pdb.Pdb):

    def _cmdloop(self) -> None:
        self.allow_kbdint = True
        self.cmdloop()
        self.allow_kbdint = False


def _get_debugger_from_tb(tb):
    printed_message = False
    while True:
        time.sleep(0.1)
        if tb.tb_frame.f_trace is None:
            _LOGGER.debug(f"Waiting for debugger to attach to {tb.tb_frame!r}")
            printed_message = True
        else:
            if printed_message:
                _LOGGER.debug(f"Debugger attached to {tb.tb_frame!r}")
            break
    debugger = tb.tb_frame.f_trace.__self__
    return debugger


PROGRAM_SHOULD_EXIT = False

def exit():
    global PROGRAM_SHOULD_EXIT
    PROGRAM_SHOULD_EXIT = True
    _to_watcher.put_nowait(('shutdown', (threading.get_ident())))


def watcher_main():
    while True:
        cmd, contents = _to_watcher.get(block=True)
        if cmd == 'tb':
            thread_id, traceback, debugger = contents
            # debugger = _get_debugger_from_tb(traceback)
            print('debugger', debugger)
        elif cmd == 'shutdown':
            thread_id = contents
            ctype_async_raise(thread_id, IntentionalExit())


class IntentionalExit(KeyboardInterrupt):
    pass


def ctype_async_raise(target_tid, exception):
    ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(target_tid),
                                                     ctypes.py_object(exception))
    # ref: http://docs.python.org/c-api/init.html#PyThreadState_SetAsyncExc
    if ret == 0:
        raise ValueError("Invalid thread ID")
    elif ret > 1:
        # Huh? Why would we notify more than one threads?
        # Because we punch a hole into C level interpreter.
        # So it is better to clean up the mess.
        ctypes.pythonapi.PyThreadState_SetAsyncExc(target_tid, NULL)
        raise SystemError("PyThreadState_SetAsyncExc failed")



WATCHER_THREAD = threading.Thread(target=watcher_main, daemon=True)
WATCHER_THREAD.start()


def wrap(func):
    @functools.wraps(func)
    def darksign_wrapper(*args, **kwargs):
        global PROGRAM_SHOULD_EXIT
        while not PROGRAM_SHOULD_EXIT:
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                if isinstance(e, KeyboardInterrupt):
                    PROGRAM_SHOULD_EXIT = True
                else:
                    traceback = sys.exc_info()[2]
                    # print(traceback)
                    # frame = sys._getframe()

                    debugger = DarksignPdb()
                    _to_watcher.put(('tb',
                                     (threading.get_ident(),
                                      traceback,
                                      debugger)))
                    debugger.reset()
                    debugger.interaction(None, traceback)
                    # breakpoint()
                # PROGRAM_SHOULD_EXIT could have been set in the debugger
                if PROGRAM_SHOULD_EXIT:
                    raise e

            _LOGGER.debug(f"Restarting {func!r}")
    return darksign_wrapper
