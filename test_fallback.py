#!/usr/bin/env python3
"""Test that fallback to pdb works when ipdb is not available"""

import sys

# Simulate ipdb not being available by blocking the import
class BlockIpdb:
    def find_module(self, fullname, path=None):
        if fullname == 'ipdb':
            return self
    
    def load_module(self, fullname):
        raise ImportError("ipdb not available")

sys.meta_path.insert(0, BlockIpdb())

# Now import hot_restart
import hot_restart

print(f"Debugger in use: {hot_restart.DEBUGGER}")
print(f"✓ Successfully fell back to {hot_restart.DEBUGGER} when ipdb is not available")