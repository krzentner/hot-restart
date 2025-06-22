#!/usr/bin/env python3
"""Manual test to demonstrate RELOAD_ALL_ON_CONTINUE functionality.

This shows how setting RELOAD_ALL_ON_CONTINUE=True causes all wrapped
functions and classes to be reloaded when continuing from any error.

Instructions:
1. Run this script
2. When it hits the debugger, edit this file:
   - Change func1 to return "func1_updated"
   - Change func2 to return "func2_updated"  
   - Change MyClass.method to return "method_updated"
   - Add a new method to MyClass:
     def new_method(self):
         return "I'm new!"
3. Type 'c' to continue
4. See that all functions and the class are reloaded
"""

import hot_restart

# Enable global reload mode
hot_restart.RELOAD_ALL_ON_CONTINUE = True

@hot_restart.wrap
def func1():
    return "func1_original"

@hot_restart.wrap
def func2():
    return "func2_original"

@hot_restart.wrap
class MyClass:
    def method(self):
        return "method_original"

@hot_restart.wrap
def main():
    print("=== Before reload ===")
    print(f"func1: {func1()}")
    print(f"func2: {func2()}")
    
    obj = MyClass()
    print(f"MyClass.method: {obj.method()}")
    
    # This will trigger the debugger
    print("\nTriggering error to allow file edits...")
    raise ValueError("Edit the file now!")
    
    # After reload, everything should be updated
    print("\n=== After reload ===")
    print(f"func1: {func1()}")
    print(f"func2: {func2()}")
    
    # Create new instance to get new methods
    new_obj = MyClass()
    print(f"MyClass.method: {new_obj.method()}")
    
    # Try the new method if it exists
    if hasattr(new_obj, 'new_method'):
        print(f"MyClass.new_method: {new_obj.new_method()}")
    
    print("\nSuccess! All functions and classes were reloaded.")

if __name__ == "__main__":
    main()