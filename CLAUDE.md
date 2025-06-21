# Hot Restart

# How It's Used:
1. Wrap target functions/modules with hot-restart decorators
2. Run program normally
3. On exception, debugger opens at crash site
4. Fix code in editor
5. Continue execution in debugger
6. Function is reloaded and execution resumes

## Development Commands

The project uses uv for package management, and [just](https://github.com/casey/just) for common development tasks. Run `just` to see all available commands. Always use `uv run` instead of `python`.

### Testing
```bash
# Run tests with both debuggers
just test-all
```
### Linting
```bash
# Run ruff linter
just lint

# Run linter with auto-fix
just lint-fix
```

### Building
```bash
# Build package with flit
just build
```

### Other Commands
```bash
# Clean up temporary files and caches
just clean
```

## Testing Approach
- Because of the global state of the python module loader, most tests need to be isolated into a subprocess using pytest-isolate
- Uses pexpect for interactive debugging session testing
- Most tests involve two source code versions: failing (`in_1.py`) and fixed (`in_2.py`)
- When adding new tests, place them in the `tests/` directory

## Key Implementation Details

### AST Transformers
- `_FindDefPath`: Locates function definitions by name and line number
- `_SuperRewriteTransformer`: Converts `super()` to `super(ClassName, self)`
- `_SurrogateTransformer`: Creates isolated modules for function compilation

### Closure Handling
- Attempts to preserve closure variables when reloading
- Limited to existing closure variables (cannot add new ones)
- Uses `__code__.co_freevars` and `__closure__` for variable mapping

## Related Files for Reference
- `hot_restart.py:47-92` - Debugger selection logic with environment variable support
- `hot_restart.py:95-124` - HotRestartPdb class definition
- `hot_restart.py:619-622` - wrap() function class handling
- `hot_restart.py:877-883` - wrap_class() function implementation
- `hot_restart.py:758-801` - Post-mortem debugger integration
- `tests/test_pexpect.py:8` - DEBUGGER_PROMPT regex pattern for both debuggers
- `tests/test_pexpect.py:11-23` - check_line_number() helper for debugger output
- `tests/test_wrap_class.py` - Tests for wrap() with classes
- `justfile` - Development commands and test configurations
