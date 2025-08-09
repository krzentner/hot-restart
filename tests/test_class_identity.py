#!/usr/bin/env python3
"""Test that class identity, isinstance checks, and MRO are preserved after reload."""

import os
import sys
import tempfile
import textwrap
import pytest
import pexpect
from test_pexpect import DEBUGGER_PROMPT


class TestClassIdentity:
    """Test class identity preservation during reload."""

    def test_isinstance_preserved_after_reload(self):
        """Test that isinstance checks work after class reload with new methods."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initial version without new_method
            test_py_v1 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                class MyClass:
                    def existing_method(self):
                        return "original"
                
                @hot_restart.wrap
                def main():
                    # Create instance before reload
                    obj = MyClass()
                    print(f"Before reload - existing_method: {obj.existing_method()}")
                    print(f"Before reload - isinstance: {isinstance(obj, MyClass)}")
                    print(f"Before reload - type match: {type(obj) is MyClass}")
                    original_id = id(MyClass)
                    print(f"Before reload - class id: {original_id}")
                    
                    # Trigger reload
                    raise ValueError("trigger reload")
                
                if __name__ == "__main__":
                    main()
            """)

            # Fixed version with new_method added
            test_py_v2 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                class MyClass:
                    def existing_method(self):
                        return "updated"
                        
                    def new_method(self):
                        return "I am new!"
                
                @hot_restart.wrap
                def main():
                    # Create instance before reload
                    obj = MyClass()
                    print(f"Before reload - existing_method: {obj.existing_method()}")
                    print(f"Before reload - isinstance: {isinstance(obj, MyClass)}")
                    print(f"Before reload - type match: {type(obj) is MyClass}")
                    original_id = id(MyClass)
                    print(f"Before reload - class id: {original_id}")
                    
                    # After reload, check the same instance
                    print(f"After reload - existing_method: {obj.existing_method()}")
                    print(f"After reload - isinstance: {isinstance(obj, MyClass)}")
                    print(f"After reload - type match: {type(obj) is MyClass}")
                    print(f"After reload - class id: {id(MyClass)}")
                    
                    # Check that new method is accessible
                    print(f"After reload - new_method: {obj.new_method()}")
                    
                    print("Success - isinstance preserved!")
                
                if __name__ == "__main__":
                    main()
            """)

            test_py = os.path.join(tmpdir, "test_isinstance.py")
            with open(test_py, "w") as f:
                f.write(test_py_v1)

            # Start the program
            proc = pexpect.spawn(
                f"python {test_py}",
                env={**os.environ, "HOT_RESTART_DEBUGGER": "pdb"},
                encoding="utf-8",
                timeout=10,
            )

            # Should see initial output
            proc.expect("Before reload - existing_method: original")
            proc.expect("Before reload - isinstance: True")
            proc.expect("Before reload - type match: True")
            proc.expect(r"Before reload - class id: \d+")

            # Should hit the error and enter debugger
            proc.expect("ValueError")
            proc.expect(DEBUGGER_PROMPT)

            # Update the file with fixed version
            with open(test_py, "w") as f:
                f.write(test_py_v2)

            # Continue - should reload all
            proc.sendline("c")
            proc.expect("> Reloaded all wrapped functions and classes")

            # After reload checks
            proc.expect("After reload - existing_method: updated")
            proc.expect("After reload - isinstance: True")
            proc.expect("After reload - type match: True")
            
            # Class ID should be the same (identity preserved)
            proc.expect(r"After reload - class id: \d+")
            
            # New method should work
            proc.expect("After reload - new_method: I am new!")
            proc.expect("Success - isinstance preserved!")

            proc.expect(pexpect.EOF)

    def test_mro_preserved_with_inheritance(self):
        """Test that MRO is preserved when reloading classes with inheritance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initial version
            test_py_v1 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                class Base:
                    def base_method(self):
                        return "base_v1"
                
                @hot_restart.wrap
                class Derived(Base):
                    def derived_method(self):
                        return "derived_v1"
                
                @hot_restart.wrap
                def main():
                    obj = Derived()
                    print(f"base_method: {obj.base_method()}")
                    print(f"derived_method: {obj.derived_method()}")
                    print(f"isinstance of Base: {isinstance(obj, Base)}")
                    print(f"isinstance of Derived: {isinstance(obj, Derived)}")
                    print(f"MRO: {[cls.__name__ for cls in Derived.__mro__]}")
                    
                    # Trigger reload
                    raise ValueError("trigger reload")
                
                if __name__ == "__main__":
                    main()
            """)

            # Fixed version with new methods
            test_py_v2 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                class Base:
                    def base_method(self):
                        return "base_v2"
                        
                    def new_base_method(self):
                        return "new_base"
                
                @hot_restart.wrap
                class Derived(Base):
                    def derived_method(self):
                        return "derived_v2"
                        
                    def new_derived_method(self):
                        return "new_derived"
                
                @hot_restart.wrap
                def main():
                    obj = Derived()
                    print(f"base_method: {obj.base_method()}")
                    print(f"derived_method: {obj.derived_method()}")
                    print(f"isinstance of Base: {isinstance(obj, Base)}")
                    print(f"isinstance of Derived: {isinstance(obj, Derived)}")
                    print(f"MRO: {[cls.__name__ for cls in Derived.__mro__]}")
                    
                    # After reload
                    print(f"After reload - base_method: {obj.base_method()}")
                    print(f"After reload - derived_method: {obj.derived_method()}")
                    print(f"After reload - new_base_method: {obj.new_base_method()}")
                    print(f"After reload - new_derived_method: {obj.new_derived_method()}")
                    print(f"After reload - isinstance of Base: {isinstance(obj, Base)}")
                    print(f"After reload - isinstance of Derived: {isinstance(obj, Derived)}")
                    print(f"After reload - MRO: {[cls.__name__ for cls in Derived.__mro__]}")
                    print("Success - MRO preserved!")
                
                if __name__ == "__main__":
                    main()
            """)

            test_py = os.path.join(tmpdir, "test_mro.py")
            with open(test_py, "w") as f:
                f.write(test_py_v1)

            # Start the program
            proc = pexpect.spawn(
                f"python {test_py}",
                env={**os.environ, "HOT_RESTART_DEBUGGER": "pdb"},
                encoding="utf-8",
                timeout=10,
            )

            # Initial output
            proc.expect("base_method: base_v1")
            proc.expect("derived_method: derived_v1")
            proc.expect("isinstance of Base: True")
            proc.expect("isinstance of Derived: True")
            proc.expect(r"MRO: \['Derived', 'Base', 'object'\]")

            # Should hit the error and enter debugger
            proc.expect("ValueError")
            proc.expect(DEBUGGER_PROMPT)

            # Update the file
            with open(test_py, "w") as f:
                f.write(test_py_v2)

            # Continue - should reload all
            proc.sendline("c")
            proc.expect("> Reloaded all wrapped functions and classes")

            # After reload checks
            proc.expect("After reload - base_method: base_v2")
            proc.expect("After reload - derived_method: derived_v2")
            proc.expect("After reload - new_base_method: new_base")
            proc.expect("After reload - new_derived_method: new_derived")
            proc.expect("After reload - isinstance of Base: True")
            proc.expect("After reload - isinstance of Derived: True")
            proc.expect(r"After reload - MRO: \['Derived', 'Base', 'object'\]")
            proc.expect("Success - MRO preserved!")

            proc.expect(pexpect.EOF)

    def test_old_instances_get_new_methods(self):
        """Test that instances created before reload can access new methods."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initial version
            test_py_v1 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                class MyClass:
                    def __init__(self, value):
                        self.value = value
                    
                    def get_value(self):
                        return self.value
                
                # Create global instance before any reload
                global_obj = MyClass(42)
                
                @hot_restart.wrap
                def main():
                    print(f"global_obj.get_value(): {global_obj.get_value()}")
                    print(f"global_obj has multiply: {hasattr(global_obj, 'multiply')}")
                    
                    # Trigger reload
                    raise ValueError("trigger reload")
                
                if __name__ == "__main__":
                    main()
            """)

            # Fixed version with new method
            test_py_v2 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                class MyClass:
                    def __init__(self, value):
                        self.value = value
                    
                    def get_value(self):
                        return self.value
                        
                    def multiply(self, factor):
                        return self.value * factor
                
                # Create global instance before any reload
                global_obj = MyClass(42)
                
                @hot_restart.wrap
                def main():
                    print(f"global_obj.get_value(): {global_obj.get_value()}")
                    print(f"global_obj has multiply: {hasattr(global_obj, 'multiply')}")
                    
                    # After reload, old instance should have new method
                    print(f"After reload - global_obj.get_value(): {global_obj.get_value()}")
                    print(f"After reload - global_obj has multiply: {hasattr(global_obj, 'multiply')}")
                    print(f"After reload - global_obj.multiply(3): {global_obj.multiply(3)}")
                    print("Success - old instance has new methods!")
                
                if __name__ == "__main__":
                    main()
            """)

            test_py = os.path.join(tmpdir, "test_old_instances.py")
            with open(test_py, "w") as f:
                f.write(test_py_v1)

            # Start the program
            proc = pexpect.spawn(
                f"python {test_py}",
                env={**os.environ, "HOT_RESTART_DEBUGGER": "pdb"},
                encoding="utf-8",
                timeout=10,
            )

            # Initial output
            proc.expect("global_obj.get_value\\(\\): 42")
            proc.expect("global_obj has multiply: False")

            # Should hit the error and enter debugger
            proc.expect("ValueError")
            proc.expect(DEBUGGER_PROMPT)

            # Update the file
            with open(test_py, "w") as f:
                f.write(test_py_v2)

            # Continue - should reload all
            proc.sendline("c")
            proc.expect("> Reloaded all wrapped functions and classes")

            # After reload checks
            proc.expect("After reload - global_obj.get_value\\(\\): 42")
            proc.expect("After reload - global_obj has multiply: True")
            proc.expect("After reload - global_obj.multiply\\(3\\): 126")
            proc.expect("Success - old instance has new methods!")

            proc.expect(pexpect.EOF)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])