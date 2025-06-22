#!/usr/bin/env python3
"""Test RELOAD_ALL_ON_CONTINUE mode that reloads all wrapped functions and classes."""

import os
import pytest
import tempfile
import textwrap
from tests.test_pexpect import check_line_number, DEBUGGER_PROMPT


class TestReloadAll:
    """Test global reload functionality."""

    def test_reload_all_on_continue(self):
        """Test that RELOAD_ALL_ON_CONTINUE reloads all wrapped functions and classes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initial version with errors
            test_py_v1 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                def func1():
                    return "func1_v1"
                
                @hot_restart.wrap
                def func2():
                    return "func2_v1"
                
                @hot_restart.wrap
                class MyClass:
                    def method(self):
                        return "method_v1"
                
                @hot_restart.wrap
                def main():
                    print(f"func1: {func1()}")
                    print(f"func2: {func2()}")
                    obj = MyClass()
                    print(f"method: {obj.method()}")
                    raise ValueError("trigger reload")
                
                if __name__ == "__main__":
                    main()
            """)

            # Fixed version - all functions and class updated
            test_py_v2 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                def func1():
                    return "func1_v2"
                
                @hot_restart.wrap
                def func2():
                    return "func2_v2"
                
                @hot_restart.wrap
                class MyClass:
                    def method(self):
                        return "method_v2"
                
                @hot_restart.wrap
                def main():
                    print(f"func1: {func1()}")
                    print(f"func2: {func2()}")
                    obj = MyClass()
                    print(f"method: {obj.method()}")
                    print("Success - all reloaded!")
                
                if __name__ == "__main__":
                    main()
            """)

            test_py = os.path.join(tmpdir, "test_reload_all.py")
            with open(test_py, "w") as f:
                f.write(test_py_v1)

            import pexpect

            # Start the program
            proc = pexpect.spawn(
                f"python {test_py}",
                env={**os.environ, "HOT_RESTART_DEBUGGER": "pdb"},
                encoding="utf-8",
                timeout=10,
            )

            # Should see initial output
            proc.expect("func1: func1_v1")
            proc.expect("func2: func2_v1")
            proc.expect("method: method_v1")

            # Should hit the error and enter debugger
            proc.expect("ValueError")
            proc.expect(DEBUGGER_PROMPT)

            # Update the file with fixed version
            with open(test_py, "w") as f:
                f.write(test_py_v2)

            # Continue - should reload all
            proc.sendline("c")
            proc.expect("> Reloaded all wrapped functions and classes")

            # Should see all updated output
            proc.expect("func1: func1_v2")
            proc.expect("func2: func2_v2")
            proc.expect("method: method_v2")
            proc.expect("Success - all reloaded!")

            proc.expect(pexpect.EOF)

    def test_reload_all_with_new_methods(self):
        """Test that new methods are available after reload."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initial version without new_method
            test_py_v1 = textwrap.dedent("""
                import hot_restart
                hot_restart.RELOAD_ALL_ON_CONTINUE = True
                
                @hot_restart.wrap
                class MyClass:
                    def existing_method(self):
                        return "existing"
                
                @hot_restart.wrap
                def main():
                    obj = MyClass()
                    print(f"existing: {obj.existing_method()}")
                    # Try to call new_method (will fail)
                    try:
                        obj.new_method()
                    except AttributeError:
                        print("new_method not found")
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
                        return "existing"
                        
                    def new_method(self):
                        return "I am new!"
                
                @hot_restart.wrap
                def main():
                    obj = MyClass()
                    print(f"existing: {obj.existing_method()}")
                    # Create new instance after reload
                    new_obj = MyClass()
                    print(f"new method: {new_obj.new_method()}")
                    print("Success!")
                
                if __name__ == "__main__":
                    main()
            """)

            test_py = os.path.join(tmpdir, "test_new_method.py")
            with open(test_py, "w") as f:
                f.write(test_py_v1)

            import pexpect

            # Start the program
            proc = pexpect.spawn(
                f"python {test_py}",
                env={**os.environ, "HOT_RESTART_DEBUGGER": "pdb"},
                encoding="utf-8",
                timeout=10,
            )

            # Should see initial output
            proc.expect("existing: existing")
            proc.expect("new_method not found")

            # Should hit the error and enter debugger
            proc.expect("ValueError")
            proc.expect(DEBUGGER_PROMPT)

            # Update the file with fixed version
            with open(test_py, "w") as f:
                f.write(test_py_v2)

            # Continue - should reload all
            proc.sendline("c")
            proc.expect("> Reloaded all wrapped functions and classes")

            # Should see new method working
            proc.expect("existing: existing")
            proc.expect("new method: I am new!")
            proc.expect("Success!")

            proc.expect(pexpect.EOF)
