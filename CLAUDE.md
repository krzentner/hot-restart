# Hot Restart - Code Intelligence Notes

## Project Overview
**hot-restart** is a Python debugging tool that enables "edit-and-continue" debugging. It allows developers to restart execution from failed functions after fixing bugs, without losing the call stack or program state.

## Core Architecture

### Main Module
- `hot_restart.py` - Single-file implementation

### Key Features
1. **Function Wrapping System**
   - `wrap()` - Decorator for individual functions
   - `wrap_class()` - Wraps all methods in a class
   - `wrap_module()` - Wraps entire modules
   - `no_wrap()` - Exclusion decorator

2. **AST-Based Code Transformation**
   - Analyzes and transforms Python code using Abstract Syntax Trees
   - Generates surrogate modules to maintain correct line numbers
   - Rewrites `super()` calls to avoid closure issues

3. **Debugger Integration**
   - Supports: ipdb (default when available), pdb (fallback), pydevd (VS Code), pudb
   - Custom `HotRestartPdb` and `HotRestartIpdb` classes extend respective debuggers
   - Post-mortem debugging with preserved stack frames
   - ipdb provides colored output and enhanced debugging features

## How It Works
1. Functions are wrapped with exception handlers
2. On exception, captures full stack trace and opens debugger
3. Developer fixes code and continues execution
4. Hot-restart reloads the fixed function while preserving state
5. Execution resumes from the reloaded function

## Development Commands

The project uses [just](https://github.com/casey/just) for common development tasks. Run `just` to see all available commands.

### Testing
```bash
# Run all tests with default debugger (ipdb if available)
just test

# Run tests with pdb specifically
just test-pdb

# Run tests with ipdb specifically  
just test-ipdb

# Run tests with both debuggers
just test-all

# Run a specific test
just test-one test_basic

# Run a specific test with pdb
just test-one-pdb test_basic
```

### Debugger Configuration
hot-restart supports both pdb and ipdb debuggers. Tests can be run with either debugger:

- **Default behavior**: Auto-detects and prefers ipdb if available, falls back to pdb
- **Force pdb**: Set `HOT_RESTART_DEBUGGER=pdb` environment variable
- **Force ipdb**: Set `HOT_RESTART_DEBUGGER=ipdb` environment variable

The test suite is designed to work with both debuggers by:
- Using a regex pattern `(?:\(Pdb\)|ipdb>)` to match both prompts
- Adapting to different output formats (ANSI codes in ipdb vs plain text in pdb)
- Using `uv run` to ensure proper environment setup

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
# Install development dependencies
just install-dev

# Run wrap class test
just test-wrap-class

# Clean up temporary files and caches
just clean
```

## Project Structure
```
hot-restart/
├── hot_restart.py          # Main implementation
├── pyproject.toml          # Project metadata and build config
├── README.md               # Documentation
├── tests/                  # Test suite
│   ├── test_pexpect.py     # Main test runner
│   ├── basic/              # Basic functionality tests
│   ├── child_class/        # Class inheritance tests
│   ├── closure/            # Closure handling tests
│   └── nested_functions/   # Nested function tests
├── dev-requirements.txt    # Development dependencies
└── shell.nix               # Nix development environment
```

## Testing Approach
- Uses pexpect for interactive debugging session testing
- Each test has two versions: failing (`in_1.py`) and fixed (`in_2.py`)
- Tests verify that code reloading works correctly in various scenarios
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

### Debugging Workflow
1. Wrap target functions/modules with hot-restart decorators
2. Run program normally
3. On exception, debugger opens at crash site
4. Fix code in editor
5. Continue execution in debugger
6. Function is reloaded and execution resumes

## Limitations
- Cannot add new closure variables without full module reload
- Limited nested function support (requires manual wrapping)
- Some advanced Python features may not work due to source rewriting
- Class instance methods have certain limitations when reloaded

## Common Use Cases
- Long-running programs where restart is expensive
- Interactive data analysis sessions
- Complex debugging scenarios requiring state preservation
- Development of algorithms with trial-and-error debugging

## Recent Changes
- **ipdb Integration**: Now attempts to use ipdb by default for better debugging experience with colored output and enhanced features. Falls back to pdb if ipdb is not available.
- **Debugger Selection**: Added environment variable support (`HOT_RESTART_DEBUGGER`) to force specific debugger selection
- **Test Suite Updates**: Modified tests to work with both pdb and ipdb debuggers
- **wrap() Enhancement**: The `wrap()` function now accepts classes in addition to functions, delegating to `wrap_class()` internally

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
