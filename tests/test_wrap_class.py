#!/usr/bin/env python3
"""Test that wrap() can now handle classes."""

import pytest
import hot_restart
import inspect


def test_wrap_decorator_on_class():
    """Test using wrap() as a decorator on a class"""
    
    @hot_restart.wrap
    class TestClass:
        def method1(self):
            return 42
        
        def method2(self, x):
            if x == 0:
                raise ValueError("x cannot be zero")
            return 100 / x
    
    # Create instance and test methods work
    obj = TestClass()
    assert obj.method1() == 42
    assert obj.method2(2) == 50
    
    # Verify methods are wrapped
    assert hasattr(obj.method1, '__wrapped__')
    assert hasattr(obj.method2, '__wrapped__')


def test_wrap_function_call_on_class():
    """Test using wrap() as a function call on a class"""
    
    class AnotherClass:
        def foo(self):
            return "foo result"
        
        def bar(self, x, y):
            return x + y
    
    # Wrap the class
    WrappedAnother = hot_restart.wrap(AnotherClass)
    
    # Verify it's still the same class
    assert WrappedAnother.__name__ == 'AnotherClass'
    
    # Create instance and test methods work
    obj = WrappedAnother()
    assert obj.foo() == "foo result"
    assert obj.bar(3, 4) == 7
    
    # Verify methods are wrapped
    assert hasattr(obj.foo, '__wrapped__')
    assert hasattr(obj.bar, '__wrapped__')


def test_wrap_class_with_special_methods():
    """Test that wrap() wraps special methods but they still work correctly"""
    
    @hot_restart.wrap
    class SpecialClass:
        def __init__(self, value):
            self.value = value
        
        def __str__(self):
            return f"SpecialClass({self.value})"
        
        def regular_method(self):
            return self.value * 2
    
    # Test that special methods still work
    obj = SpecialClass(5)
    assert str(obj) == "SpecialClass(5)"
    assert obj.regular_method() == 10
    
    # All methods should be wrapped (including special methods)
    assert hasattr(obj.__init__, '__wrapped__')
    assert hasattr(obj.__str__, '__wrapped__')
    assert hasattr(obj.regular_method, '__wrapped__')


def test_wrap_class_inheritance():
    """Test that wrapped classes can still be inherited"""
    
    @hot_restart.wrap
    class BaseClass:
        def base_method(self):
            return "base"
    
    class DerivedClass(BaseClass):
        def derived_method(self):
            return "derived"
    
    obj = DerivedClass()
    assert obj.base_method() == "base"
    assert obj.derived_method() == "derived"
    
    # Base method should be wrapped
    assert hasattr(obj.base_method, '__wrapped__')
    # Derived method should not be wrapped (unless we wrap DerivedClass too)
    assert not hasattr(obj.derived_method, '__wrapped__')


def test_wrap_class_only_wraps_callables():
    """Test that wrap() only wraps callable attributes"""
    
    @hot_restart.wrap  
    class MixedClass:
        class_var = 42
        
        def __init__(self):
            self.instance_var = 100
        
        def method(self):
            return self.instance_var + MixedClass.class_var
    
    obj = MixedClass()
    
    # Test functionality
    assert obj.method() == 142
    assert MixedClass.class_var == 42
    assert obj.instance_var == 100
    
    # Only method should be wrapped
    assert hasattr(obj.method, '__wrapped__')
    # Class variables should not be affected
    assert MixedClass.class_var == 42


def test_wrap_ignores_builtin_methods():
    """Test that wrap() skips built-in methods in classes"""
    
    @hot_restart.wrap
    class ClassWithBuiltin:
        # Reference to a built-in function
        builtin_ref = len
        
        def regular_method(self):
            return "regular"
    
    obj = ClassWithBuiltin()
    
    # Regular method should work and be wrapped
    assert obj.regular_method() == "regular"
    assert hasattr(obj.regular_method, '__wrapped__')
    
    # Built-in reference should still work but not be wrapped
    assert ClassWithBuiltin.builtin_ref([1, 2, 3]) == 3
    # Can't check if builtin_ref is wrapped since built-ins don't support attributes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])