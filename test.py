import hot_restart
import functools
import inspect


@hot_restart.wrap
@functools.cache
def outer():
    print('in outer')
    x = 1
    y = 1 + x
    inner_inst = Inner()
    try:
        z, q = inner_inst.inner(y, k=[])
    except AssertionError as e:
        raise e
    return y + z

print('IN TEST MODULE')

class Parent:

    def inner(self):
        print('in parent.inner')

class Inner(Parent):

    def inner(self, y_inner, k='test'):
        super().inner()
        print(self)
        print('in inner')
        z = y_inner ** 2
        mini()
        k.append(z)
        return z ** 2, k

@hot_restart.no_wrap
def mini():
    assert False

hot_restart.wrap_module()
outer()
