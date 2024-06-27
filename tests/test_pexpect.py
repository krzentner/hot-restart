from tempfile import NamedTemporaryFile

import pexpect


def mktmp(test_dir):
    return NamedTemporaryFile(suffix=f"_{test_dir}.py", mode="w")


def copy(test_dir, fname, tmp):
    tmp.seek(0)
    tmp.truncate()
    fname = f"tests/{test_dir}/{fname}"
    with open(fname) as f:
        content = f.read()
        print(f"Copying content from {fname} to {tmp.name}")
        print(content)
        tmp.write(content)
        tmp.flush()
    with open(tmp.name) as f2:
        print(f"Reading back from {tmp.name}:")
        print(f2.read())


def exp(child, pattern):
    child.expect(pattern, timeout=0.5)
    print(child.before.decode())


def test_basic():
    test_dir = "basic"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("python", [tmp.name])
    exp(child, "(Pdb)")
    assert b"13  ->" in child.before
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")
    child.expect("in inner: 20", timeout=0.5)


def test_basic_twice():
    test_dir = "basic"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("python", [tmp.name])

    exp(child, "(Pdb)")
    assert b"13  ->" in child.before
    child.sendline("c")

    exp(child, "(Pdb)")
    assert b"13  ->" in child.before
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")

    child.expect("in inner: 20", timeout=0.5)


def test_basic_reload_module():
    test_dir = "basic"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("python", [tmp.name])

    exp(child, "(Pdb)")
    assert b"13  ->" in child.before
    child.sendline("hot_restart.reload_module()")
    exp(child, "(Pdb)")
    child.sendline("c")

    exp(child, "(Pdb)")
    copy(test_dir, "in_2.py", tmp)
    child.sendline("hot_restart.reload_module()")
    exp(child, "(Pdb)")
    child.sendline("c")

    child.expect("in inner: 20", timeout=0.5)


def test_child_class():
    test_dir = "child_class"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("python", [tmp.name])
    exp(child, "(Pdb)")
    assert b"15  ->" in child.before
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")
    child.expect("result 49", timeout=0.5)


def test_closure():
    test_dir = "closure"
    tmp = mktmp(test_dir)
    copy(test_dir, "in_1.py", tmp)
    child = pexpect.spawn("python", [tmp.name])
    exp(child, "(Pdb)")
    assert b"10  ->" in child.before
    copy(test_dir, "in_2.py", tmp)
    child.sendline("c")
    child.expect("y 2 x 1 test", timeout=0.5)


if __name__ == "__main__":
    # test_basic()
    # test_basic_twice()
    test_basic_reload_module()
    # test_child_class()
    # test_closure()
