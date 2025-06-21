import hot_restart
import functools


@hot_restart.wrap
@functools.cache
def outer():
    print("in outer")
    x = 1
    y = 1 + x
    inner_inst = Inner()
    try:
        z, q = inner_inst.inner(y, k=[])
    except AssertionError as e:
        raise e
    return y + z


print("IN TEST MODULE")


class Parent:
    def inner(self):
        print("in parent.inner")


class Inner(Parent):
    def inner(self, y_inner, k="test"):
        super().inner()
        print(self)
        print("in inner")

        # hi :)
        z = y_inner**2
        mini()
        k.append(z)
        return z**2, k


@hot_restart.no_wrap
def mini():
    # hi :)
    assert False


def outer_fn():
    x, y = 1, 2

    @hot_restart.wrap
    @functools.cache
    def inner_fn(s, y):
        assert False
        print("y", y)
        print("x", x)
        print(s)

    inner_fn("test", 1)
    inner_fn("test", 2)


@hot_restart.wrap
def main():
    Inner().inner(10)
    outer_fn()


hot_restart.wrap_module()
if not hot_restart.is_restarting_module():
    main()
