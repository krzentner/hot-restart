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
   - Supports: pdb (default), pydevd (VS Code), pudb
   - Custom `HotRestartPdb` extends standard pdb
   - Post-mortem debugging with preserved stack frames

## How It Works
1. Functions are wrapped with exception handlers
2. On exception, captures full stack trace and opens debugger
3. Developer fixes code and continues execution
4. Hot-restart reloads the fixed function while preserving state
5. Execution resumes from the reloaded function

## Development Commands

### Testing
```bash
# Run all tests
pytest tests/test_pexpect.py

# Run specific test
pytest tests/test_pexpect.py::test_basic
```

### Linting
```bash
# Run ruff linter
ruff check hot_restart.py
```

### Building
```bash
# Build package with flit
flit build
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

## Related Files for Reference
- `hot_restart.py:85-120` - Main wrap() function implementation
- `hot_restart.py:400-500` - AST transformation logic
- `hot_restart.py:700-800` - Debugger integration
- `tests/test_pexpect.py:50-100` - Test infrastructure setup
