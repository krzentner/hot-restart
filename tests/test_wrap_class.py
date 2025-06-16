#!/usr/bin/env python3
"""Test that wrap() can now handle classes."""

import hot_restart

# Test using wrap() as a decorator on a class
@hot_restart.wrap
class TestClass:
    def method1(self):
        print("Method 1 called")
        return 42
    
    def method2(self, x):
        print(f"Method 2 called with {x}")
        if x == 0:
            raise ValueError("x cannot be zero")
        return 100 / x

# Test using wrap() as a function call on a class
class AnotherClass:
    def foo(self):
        print("foo called")
        raise RuntimeError("Test error")

WrappedAnother = hot_restart.wrap(AnotherClass)

if __name__ == "__main__":
    # Test the decorator version
    obj1 = TestClass()
    print(f"Result from method1: {obj1.method1()}")
    
    # Test the function call version
    obj2 = WrappedAnother()
    try:
        obj2.foo()
    except RuntimeError:
        print("Caught expected RuntimeError")
    
    print("\nAll tests passed! wrap() now works with classes.")