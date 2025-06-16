"""Test module for wrap_modules - test_utils"""

def util_func1():
    return "util1"

def util_func2(data):
    return f"processed: {data}"

# Global variable (should not be wrapped)
CONSTANT = 42