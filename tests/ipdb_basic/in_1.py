import hot_restart

@hot_restart.wrap
def add(x, y):
    result = x + y
    assert result == 5  # This will fail when called with 2, 2
    return result

print(f"Using debugger: {hot_restart.DEBUGGER}")
print(add(2, 2))