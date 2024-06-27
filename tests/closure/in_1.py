import functools


def outer_fn():
    x, y = 1, 2

    @functools.cache
    @hot_restart.wrap
    def inner_fn(s):
        assert False
        print("y", y)
        print("x", x)
        print(s)

    inner_fn("test")
    inner_fn("test")


import hot_restart

if not hot_restart.is_restarting_module():
    outer_fn()
