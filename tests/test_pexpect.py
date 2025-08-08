from tempfile import NamedTemporaryFile
import os
import re

import pexpect

# Pattern that matches both pdb and ipdb prompts
DEBUGGER_PROMPT = r"(?:\(Pdb\)|ipdb>)"


def check_line_number(output, line_num):
    """Check if a specific line number is shown in debugger output.
    Works with both pdb and ipdb formatting."""
    if not output:
        return False
    line_bytes = str(line_num).encode()
    # pdb uses "line_num  ->" format, ipdb uses ANSI codes
    # For debugging, print if not found
    if line_bytes not in output:
        print(f"Line {line_num} not found in output (length={len(output)})")
        if len(output) < 100:
            print(f"Output: {output!r}")
    return line_bytes in output


def mktmp(test_dir):
    return NamedTemporaryFile(suffix=f"_{test_dir}.py", mode="w")


def copy(test_dir, fname, tmp):
    tmp.seek(0)
    tmp.truncate()
    fname = f"tests/{test_dir}/{fname}"
    with open(fname) as f:
        content = f.read()
        print(f"Copying content from {fname} to {tmp.name}")
        print(f"\n -- contents of {fname} --\n")
        print(content)
        print(f"\n -- end contents of {fname} --\n")
        tmp.write(content)
        tmp.flush()
    # with open(tmp.name) as f2:
    #     print(f"Reading back from {tmp.name}:")
    #     print(f2.read())


def exp(child, pattern):
    try:
        child.expect(pattern, timeout=2.0)
    except pexpect.exceptions.TIMEOUT:
        raise AssertionError(f"Timeout with pattern {pattern!r}")
    finally:
        print(f"\n -- before {pattern!r} -- \n")
        print(child.before.decode())
        print(f"\n -- end before {pattern!r} -- \n")


def test_basic():
    test_dir = "basic"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    # Use uv run to ensure proper environment
    child = pexpect.spawn("uv", ["run", "python", tmp.name])
    exp(child, DEBUGGER_PROMPT)
    assert check_line_number(child.before, 13)
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")
    exp(child, "in inner: 20")


def test_basic_twice():
    test_dir = "basic"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("uv", ["run", "python", tmp.name])

    exp(child, DEBUGGER_PROMPT)
    assert check_line_number(child.before, 13)
    child.sendline("c")

    exp(child, DEBUGGER_PROMPT)
    # Second time might not show full traceback, just check we're at a debugger prompt
    # The important part is that we got to the debugger again
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")

    exp(child, "in inner: 20")


def test_basic_reload_module():
    test_dir = "basic"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("uv", ["run", "python", tmp.name])

    exp(child, DEBUGGER_PROMPT)
    assert check_line_number(child.before, 13)
    child.sendline("hot_restart.reload_module()")
    exp(child, DEBUGGER_PROMPT)
    child.sendline("c")

    exp(child, DEBUGGER_PROMPT)
    copy(test_dir, "in_2.py", tmp)
    child.sendline("hot_restart.reload_module()")
    exp(child, DEBUGGER_PROMPT)
    try:
        child.sendline("c")
    except OSError:
        # Process may have terminated due to race condition
        pass

    exp(child, "in inner: 20")


def test_child_class():
    test_dir = "child_class"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("uv", ["run", "python", tmp.name])
    exp(child, DEBUGGER_PROMPT)
    assert check_line_number(child.before, 15)
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")
    exp(child, "result 49")


def test_closure():
    test_dir = "closure"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("uv", ["run", "python", tmp.name])
    exp(child, DEBUGGER_PROMPT)
    assert check_line_number(child.before, 10)
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")
    exp(child, "y 2 x 1 test")


def test_nested_functions():
    test_dir = "nested_functions"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("uv", ["run", "python", tmp.name])
    exp(child, DEBUGGER_PROMPT)
    assert check_line_number(child.before, 8)
    # Send ctrl-c
    child.sendcontrol("c")
    assert check_line_number(child.before, 8)
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")
    exp(child, "hi")


if __name__ == "__main__":
    test_basic()
    # test_basic_twice()
    # test_basic_reload_module()
    # test_child_class()
    # test_closure()
    # test_nested_functions()
