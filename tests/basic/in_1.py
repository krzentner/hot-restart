import hot_restart


def outer():
    y = 10
    print("in outer", y)
    inner(y + 10)


# extra
# lines
def inner(x):
    assert False, "whoops"
    print("in inner:", x)


hot_restart.wrap_module()

if __name__ == "__main__" and not hot_restart.is_restarting_module():
    outer()
