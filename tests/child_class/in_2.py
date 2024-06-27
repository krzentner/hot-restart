class Parent:
    def inner(self, y):
        print("in parent.inner", y)
        return y + 5


class Child(Parent):
    def inner(self, y):
        print("in inner")
        z = super().inner(y)
        return z**2


import hot_restart

hot_restart.wrap_module()
print(Child().inner(2))
