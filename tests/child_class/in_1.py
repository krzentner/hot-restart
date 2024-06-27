print("hi :)")


class Parent:
    def inner(self, y):
        print("in parent.inner", y)
        return y + 5


# extra line
class Child(Parent):
    def inner(self, y):
        print("in inner")
        z = y**2
        [][1]
        return z**2


import hot_restart

hot_restart.wrap_module()
print("result", Child().inner(2))
