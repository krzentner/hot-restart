import darksign


@darksign.wrap
def outer():
    print('in outer')
    x = 1
    y = 1 + x
    try:
        z, q = inner(y, k=[])
    except AssertionError as e:
        raise e
    return y + z

print('hi')

@darksign.wrap
def inner(y_inner, k='test'):
    print('in inner')
    z = y_inner ** 2
    assert False
    k.append(z)
    return z ** 2, k


outer()
