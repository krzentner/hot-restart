#!/usr/bin/env python
"""Test script to check if warnings are suppressed when wrapping modules/classes"""
import sys
import io
import logging
import hot_restart

# Capture logging output
log_capture = io.StringIO()

# Remove existing handlers to prevent duplicate output
hot_restart._LOGGER.handlers.clear()

handler = logging.StreamHandler(log_capture)
handler.setLevel(logging.ERROR)
hot_restart._LOGGER.addHandler(handler)
hot_restart._LOGGER.setLevel(logging.ERROR)

# Lambda function - won't have source
my_lambda = lambda x: x + 1

# Built-in function reference
my_builtin = print

# Regular function that can be wrapped
def regular_function():
    return "This function has source"

# Class with methods
class MyClass:
    # Lambda as class attribute
    class_lambda = lambda self, x: x * 2
    
    def regular_method(self):
        return "Regular method"
    
    # Built-in reference as attribute
    builtin_ref = len

print("Testing wrap_module...")
hot_restart.wrap_module()

# Get the captured log output
module_wrap_output = log_capture.getvalue()
print(f"Module wrap warnings: {repr(module_wrap_output)}")

# Clear the log for next test
log_capture.truncate(0)
log_capture.seek(0)

print("\nTesting explicit wrap...")
# Try explicit wrapping - should show warnings
try:
    wrapped_lambda = hot_restart.wrap(lambda y: y * 2)
except:
    pass

try:
    wrapped_builtin = hot_restart.wrap(print)
except:
    pass

# Get the captured log output  
explicit_wrap_output = log_capture.getvalue()
print(f"Explicit wrap warnings: {repr(explicit_wrap_output)}")

# Check results
if "Could not" in module_wrap_output:
    print("FAIL: Found warnings in module wrap output")
    sys.exit(1)
    
if "Could not" not in explicit_wrap_output:
    print("FAIL: No warnings found in explicit wrap output")
    sys.exit(1)

print("\nSUCCESS: Warnings only shown for explicit wrap, not module/class wrap")