import hot_restart


@hot_restart.wrap
def add(x, y):
    result = x + y
    assert result == 4  # Fixed assertion
    return result


print(f"Using debugger: {hot_restart.DEBUGGER}")
print(add(2, 2))
