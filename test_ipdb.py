#!/usr/bin/env python3
"""Test ipdb integration with hot_restart"""

import hot_restart
hot_restart.wrap_module()

@hot_restart.wrap
def test_function():
    x = 1
    y = 2
    # This will cause an error
    z = x / 0
    return z

if __name__ == "__main__":
    # Check which debugger is being used
    print(f"Using debugger: {hot_restart.DEBUGGER}")
    
    try:
        result = test_function()
    except Exception as e:
        print(f"Caught exception: {e}")