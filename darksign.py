import ctypes
import sys
import queue
import logging
import time
import functools
import threading
import pdb
import termios
import asyncio

old_except_hook = None

_LOGGER = logging.getLogger('darksign')
_LOGGER.addHandler(logging.StreamHandler(sys.stderr))
_LOGGER.setLevel(logging.DEBUG)

_to_watcher = queue.Queue()


async def connect_stdin_stdout():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    w_transport, w_protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
    writer = asyncio.StreamWriter(w_transport, w_protocol, reader, loop)
    return reader, writer


class DarksignPdb(pdb.Pdb):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.async_task_loop = None

    def _cmdloop(self) -> None:
        self.allow_kbdint = True
        self.cmdloop()
        # try:
        #     self.async_task_loop = self.async_cmdloop()
        #     asyncio.run(self.async_task_loop)
        # finally:
        #     termios.tcflush(sys.stdin, termios.TCIFLUSH)
        self.allow_kbdint = False

    async def async_cmdloop(self, intro=None):
        reader, writer = await connect_stdin_stdout()
        self.preloop()
        if self.use_rawinput and self.completekey:
            try:
                print('setting up readline')
                import readline
                self.old_completer = readline.get_completer()
                readline.set_completer(self.complete)
                readline.parse_and_bind(self.completekey+": complete")
                print('set up readline')
            except ImportError:
                pass
        try:
            if intro is not None:
                self.intro = intro
            if self.intro:
                writer.write((str(self.intro)+"\n").encode())
            stop = None
            while not stop:
                if self.cmdqueue:
                    line = self.cmdqueue.pop(0)
                else:
                    writer.write(self.prompt.encode())
                    await writer.drain()
                    line = ''
                    in_bytes = b''
                    while '\n' not in line:
                        in_bytes = await reader.readline()
                        line += in_bytes.decode()
                        print('in_bytes', in_bytes)
                    if not len(in_bytes):
                        line = 'EOF'
                    else:
                        line = line.rstrip('\r\n')
                line = self.precmd(line)
                stop = self.onecmd(line)
                stop = self.postcmd(stop, line)
            self.postloop()
        finally:
            if self.use_rawinput and self.completekey:
                try:
                    import readline
                    readline.set_completer(self.old_completer)
                except ImportError:
                    pass


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
            # time.sleep(2.0)
            # print("Code was patched, interrupting debugger...")
            # ctype_async_raise(thread_id, CodePatched())
            # debugger = _get_debugger_from_tb(traceback)
            # print('debugger', debugger)

class CodePatched(Exception):
    pass


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
                    if traceback is not None:
                        debugger.reset()
                        debugger.setup(traceback.tb_frame, traceback)
                        try:
                            debugger._cmdloop()
                        except KeyboardInterrupt:
                            PROGRAM_SHOULD_EXIT = True
                            raise e
                    # breakpoint()
                # PROGRAM_SHOULD_EXIT could have been set in the debugger
                if PROGRAM_SHOULD_EXIT:
                    raise e

            _LOGGER.debug(f"Restarting {func!r}")
    return darksign_wrapper
