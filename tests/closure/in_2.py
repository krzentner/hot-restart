import functools


def outer_fn():
    x, y = 1, 2

    @functools.cache
    @hot_restart.wrap
    def inner_fn(s):
        print("y", y, "x", x, s)
        print("x", x)

    inner_fn("test")
    inner_fn("cached")


import hot_restart

if not hot_restart.is_restarting_module():
    outer_fn()
