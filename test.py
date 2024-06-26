import darksign


@darksign.wrap
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

print('hi')

class Parent:

    def inner(self):
        print('in parent.inner')

class Inner(Parent):

    @darksign.wrap
    def inner(self, y_inner, k='test'):
        super().inner()
        print(self)
        print('in inner')
        z = y_inner ** 2
        mini()
        k.append(z)
        return z ** 2, k

def mini():
    assert False

outer()
