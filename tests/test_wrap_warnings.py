#!/usr/bin/env python
import sys
import os
import pexpect
import re

# Test that wrap_module doesn't show warnings for functions without source
def test_module_wrap_no_warnings():
    print("Testing module wrap - should not show warnings for lambdas/builtins")
    
    # Run the module wrap test
    child = pexpect.spawn(
        sys.executable,
        [os.path.join(os.path.dirname(__file__), "wrap_warnings", "module_wrap_test.py")],
        encoding="utf-8",
        timeout=10
    )
    
    # Collect all output
    output = ""
    try:
        while True:
            output += child.read_nonblocking(size=1000, timeout=1)
    except pexpect.TIMEOUT:
        pass
    except pexpect.EOF:
        pass
    
    child.close()
    
    # Print output for debugging
    print(f"Module wrap output:\n{output}\n")
    
    # Check that no "Could not wrap" errors appear in output
    assert "Could not wrap" not in output, f"Found unwanted warning in output:\n{output}"
    assert "could not get source" not in output, f"Found unwanted warning in output:\n{output}"
    
    # Verify expected output is there
    assert "Lambda result: 6" in output, f"Expected output not found:\n{output}"
    assert "Regular function: This function has source" in output
    assert "Class method: Regular method" in output
    
    print("✓ Module wrap test passed - no warnings for lambdas/builtins")


# Test that explicit @wrap does show warnings
def test_explicit_wrap_shows_warnings():
    print("\nTesting explicit wrap - should show warnings for lambdas/builtins")
    
    # Run the explicit wrap test
    child = pexpect.spawn(
        sys.executable,
        [os.path.join(os.path.dirname(__file__), "wrap_warnings", "explicit_wrap_test.py")],
        encoding="utf-8",
        timeout=10
    )
    
    # Collect all output
    output = ""
    try:
        while True:
            output += child.read_nonblocking(size=1000, timeout=1)
    except pexpect.TIMEOUT:
        pass
    except pexpect.EOF:
        pass
    
    child.close()
    
    # Print output for debugging
    print(f"Explicit wrap output:\n{output}\n")
    
    # Check that warnings DO appear for explicit wrap
    assert "Could not" in output, \
        f"Expected warning not found in output:\n{output}"
    
    # Verify the functions still work despite warnings
    assert "Wrapped lambda result: 6" in output
    assert "Regular function: This function has source" in output
    
    print("✓ Explicit wrap test passed - warnings shown for lambdas/builtins")


if __name__ == "__main__":
    test_module_wrap_no_warnings()
    test_explicit_wrap_shows_warnings()
    print("\n✅ All wrap warning tests passed!")