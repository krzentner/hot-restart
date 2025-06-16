#!/usr/bin/env python3
"""Simple test to verify ipdb is being used"""

import hot_restart

# Check which debugger is being used
print(f"Debugger in use: {hot_restart.DEBUGGER}")

# Verify ipdb-specific features are available
if hot_restart.DEBUGGER == "ipdb":
    print("✓ ipdb is successfully configured as the default debugger")
    print("✓ ipdb will provide colored output and enhanced debugging features")
else:
    print(f"✗ Expected ipdb but got {hot_restart.DEBUGGER}")