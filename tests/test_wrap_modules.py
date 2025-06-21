#!/usr/bin/env python3
"""Test that wrap_modules() can wrap multiple modules using fnmatch patterns."""

import pytest
import sys
from pathlib import Path

# Add test modules to path
test_modules_path = Path(__file__).parent / "wrap_modules_test"
sys.path.insert(0, str(test_modules_path))


@pytest.mark.isolate
def test_wrap_modules_all():
    """Test wrapping all modules with '*' pattern"""
    import hot_restart
    import myapp_module1
    import myapp_module2
    import other_module

    # Wrap all modules matching our test pattern
    hot_restart.wrap_modules("*module*")

    # Check that functions are wrapped
    assert hasattr(myapp_module1.func1, "__wrapped__")
    assert hasattr(myapp_module1.func2, "__wrapped__")
    assert hasattr(myapp_module2.another_func, "__wrapped__")
    assert hasattr(other_module.other_func, "__wrapped__")

    # Check that classes are wrapped
    obj1 = myapp_module1.MyClass1()
    assert hasattr(obj1.method1, "__wrapped__")
    assert hasattr(obj1.method2, "__wrapped__")

    obj2 = myapp_module2.AnotherClass(42)
    assert hasattr(obj2.get_value, "__wrapped__")

    # Functions should still work
    assert myapp_module1.func1() == "myapp1"
    assert myapp_module1.func2(2, 3) == 5
    assert myapp_module2.another_func() == "myapp2"
    assert other_module.other_func() == "other"


@pytest.mark.isolate
def test_wrap_modules_prefix_pattern():
    """Test wrapping modules with prefix pattern like 'myapp*'"""
    import hot_restart
    import myapp_module1
    import myapp_module2
    import other_module

    # Wrap only modules starting with 'myapp'
    hot_restart.wrap_modules("myapp*")

    # Check that only myapp modules are wrapped
    assert hasattr(myapp_module1.func1, "__wrapped__")
    assert hasattr(myapp_module2.another_func, "__wrapped__")
    assert not hasattr(other_module.other_func, "__wrapped__")

    # All functions should still work
    assert myapp_module1.func1() == "myapp1"
    assert myapp_module2.another_func() == "myapp2"
    assert other_module.other_func() == "other"


@pytest.mark.isolate
def test_wrap_modules_suffix_pattern():
    """Test wrapping modules with suffix pattern like '*_utils'"""
    import hot_restart
    import test_utils
    import test_helpers
    import other_module

    # Wrap only modules ending with '_utils'
    hot_restart.wrap_modules("*_utils")

    # Check that only utils modules are wrapped
    assert hasattr(test_utils.util_func1, "__wrapped__")
    assert hasattr(test_utils.util_func2, "__wrapped__")
    assert not hasattr(test_helpers.helper_func, "__wrapped__")
    assert not hasattr(other_module.other_func, "__wrapped__")

    # Check that constants are not wrapped
    assert test_utils.CONSTANT == 42


@pytest.mark.isolate
def test_wrap_modules_middle_pattern():
    """Test wrapping modules with middle pattern like 'test_*'"""
    import hot_restart
    import test_utils
    import test_helpers
    import other_module

    # Wrap modules matching 'test_*'
    hot_restart.wrap_modules("test_*")

    # Check that matching modules are wrapped
    assert hasattr(test_utils.util_func1, "__wrapped__")
    assert hasattr(test_helpers.helper_func, "__wrapped__")
    assert not hasattr(other_module.other_func, "__wrapped__")

    # Check class methods - note that staticmethod/classmethod descriptors
    # themselves won't have __wrapped__, but the underlying functions will be wrapped
    # when called through an instance
    obj = test_helpers.HelperClass()
    # Regular instance can call static method
    assert test_helpers.HelperClass.static_method() == "static"
    assert test_helpers.HelperClass.class_method() == "class"


@pytest.mark.isolate
def test_wrap_modules_nested_pattern():
    """Test wrapping nested modules with pattern like 'app.*.*'"""
    import hot_restart
    from app.core import models as app_core_models
    from app.utils import helpers as app_utils_helpers
    from app import single as app_single
    from other.core import models as other_core_models

    # Wrap only modules matching 'app.*.*' (two levels deep)
    hot_restart.wrap_modules("app.*.*")

    # Check that only two-level deep app modules are wrapped
    assert hasattr(app_core_models.model_func, "__wrapped__")
    assert hasattr(app_utils_helpers.helper_func, "__wrapped__")

    # Single level and other modules should not be wrapped
    assert not hasattr(app_single.single_func, "__wrapped__")
    assert not hasattr(other_core_models.other_model_func, "__wrapped__")

    # Check class wrapping
    model = app_core_models.Model()
    assert hasattr(model.save, "__wrapped__")


@pytest.mark.isolate
def test_wrap_modules_with_classes():
    """Test that wrap_modules also wraps classes in matched modules"""
    import hot_restart
    import myapp_module1

    # Wrap the module
    hot_restart.wrap_modules("myapp_module1")

    # Check that function is wrapped
    assert hasattr(myapp_module1.func1, "__wrapped__")

    # Check that class methods are wrapped
    obj = myapp_module1.MyClass1()
    assert hasattr(obj.method1, "__wrapped__")
    assert hasattr(obj.method2, "__wrapped__")

    # Everything should still work
    assert myapp_module1.func1() == "myapp1"
    assert obj.method1() == "method1"
    assert obj.method2(5) == 10


@pytest.mark.isolate
def test_wrap_modules_no_match():
    """Test that wrap_modules does nothing when no modules match"""
    import hot_restart
    import other_module

    # Try to wrap with pattern that doesn't match
    hot_restart.wrap_modules("nonexistent*")

    # Function should not be wrapped
    assert not hasattr(other_module.other_func, "__wrapped__")

    # Function should still work
    assert other_module.other_func() == "other"


@pytest.mark.isolate
def test_wrap_modules_skips_no_wrap():
    """Test that wrap_modules respects @no_wrap decorator"""
    import hot_restart
    import nowrap_module

    # Wrap the module
    hot_restart.wrap_modules("nowrap_module")

    # Check that no_wrap function is not wrapped
    assert not hasattr(nowrap_module.no_wrap_func, "__wrapped__")

    # Check that regular function is wrapped
    assert hasattr(nowrap_module.regular_func, "__wrapped__")

    # Check that no_wrap class is not wrapped
    no_wrap_obj = nowrap_module.NoWrapClass()
    assert not hasattr(no_wrap_obj.method, "__wrapped__")

    # Check that regular class is wrapped
    regular_obj = nowrap_module.RegularClass()
    assert hasattr(regular_obj.method, "__wrapped__")

    # All should still work
    assert nowrap_module.no_wrap_func() == "no_wrap"
    assert nowrap_module.regular_func() == "regular"
    assert no_wrap_obj.method() == "no_wrap_method"
    assert regular_obj.method() == "regular_method"


@pytest.mark.isolate
def test_wrap_modules_multiple_patterns():
    """Test calling wrap_modules multiple times with different patterns"""
    import hot_restart
    import myapp_module1
    import test_utils
    import other_module

    # Wrap modules with different patterns
    hot_restart.wrap_modules("myapp*")
    hot_restart.wrap_modules("*_utils")

    # Check that correct modules are wrapped
    assert hasattr(myapp_module1.func1, "__wrapped__")
    assert hasattr(test_utils.util_func1, "__wrapped__")
    assert not hasattr(other_module.other_func, "__wrapped__")


@pytest.mark.isolate
def test_wrap_modules_already_wrapped():
    """Test that wrap_modules doesn't double-wrap already wrapped functions"""
    import hot_restart
    import myapp_module1

    # Wrap it twice
    hot_restart.wrap_modules("myapp_module1")
    hot_restart.wrap_modules("myapp_module1")

    # Should still have only one level of wrapping
    assert hasattr(myapp_module1.func1, "__wrapped__")
    # The wrapped function should not have __wrapped__ (indicating double wrapping)
    assert not hasattr(myapp_module1.func1.__wrapped__, "__wrapped__")

    # Function should still work
    assert myapp_module1.func1() == "myapp1"


@pytest.mark.isolate
def test_wrap_modules_builtin_exclusion():
    """Test that wrap_modules doesn't wrap built-in modules"""
    import hot_restart

    # This should not raise any errors even though it might match built-in module names
    hot_restart.wrap_modules("os")
    hot_restart.wrap_modules("sys")

    # Built-in functions should not be wrapped (they don't have __file__)
    import os

    assert not hasattr(os.path.join, "__wrapped__")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
