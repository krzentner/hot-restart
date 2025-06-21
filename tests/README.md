# Hot Restart Test Suite

This directory contains comprehensive unit tests for the `hot-restart` module, covering all major components and functionality.

## Test Structure

### Core Test Files

- **`test_ast_classes.py`** - Unit tests for AST transformer classes
  - `FindDefPath` - Function definition path finder
  - `SuperRewriteTransformer` - Super() call transformer
  - `SurrogateTransformer` - Surrogate source generator
  - `LineNoResetter` - Line number reset utility
  - `FindTargetNode` - Target node finder

- **`test_debugger_classes.py`** - Unit tests for debugger integration
  - `HotRestartPdb` - Custom PDB debugger class
  - `ReloadException` - Custom exception handling
  - Debugger selection and post-mortem functionality
  - Traceback handling utilities

- **`test_utility_functions.py`** - Unit tests for utility functions
  - Source code parsing and transformation
  - Function reloading mechanisms
  - File operations and temporary file handling
  - Module-level utilities

- **`test_integration.py`** - Integration tests
  - End-to-end functionality testing
  - Real-world usage patterns
  - Error handling and edge cases
  - Thread safety and memory management

### Existing Test Files

- **`test_wrap_class.py`** - Tests for class wrapping functionality
- **`test_wrap_modules.py`** - Tests for module wrapping
- **`test_wrap_warnings.py`** - Tests for warning handling
- **`test_ipdb_integration.py`** - Tests for ipdb integration
- **`test_pexpect.py`** - Interactive debugging tests using pexpect

## Running Tests

### Run All Tests
```bash
just test
```

### Run Specific Test Categories
```bash
# Run only unit tests for AST classes
pytest tests/test_ast_classes.py -v

# Run only debugger tests
pytest tests/test_debugger_classes.py -v

# Run only utility function tests
pytest tests/test_utility_functions.py -v

# Run integration tests
pytest tests/test_integration.py -v
```

### Run Individual Test Classes
```bash
# Test specific AST class
pytest tests/test_ast_classes.py::TestFindDefPath -v

# Test debugger functionality
pytest tests/test_debugger_classes.py::TestHotRestartPdb -v
```

### Run with Different Debuggers
```bash
# Test with pdb
HOT_RESTART_DEBUGGER=pdb pytest tests/ -v

# Test with ipdb (if available)
HOT_RESTART_DEBUGGER=ipdb pytest tests/ -v
```

## Test Coverage

### AST Classes (test_ast_classes.py)
- ✅ Function definition path finding
- ✅ Super() call transformation
- ✅ Surrogate source generation
- ✅ Line number handling
- ✅ Target node detection
- ✅ Nested function and class handling

### Debugger Classes (test_debugger_classes.py)
- ✅ Custom PDB debugger initialization
- ✅ Debugger selection logic
- ✅ Post-mortem debugging setup
- ✅ Exception handling
- ✅ Traceback manipulation

### Utility Functions (test_utility_functions.py)
- ✅ Source code parsing
- ✅ Function reloading
- ✅ File operations
- ✅ Module utilities
- ✅ Error handling

### Integration Tests (test_integration.py)
- ✅ End-to-end wrapping functionality
- ✅ Real-world usage patterns
- ✅ API compatibility
- ✅ Thread safety
- ✅ Memory management

## Key Testing Principles

### 1. Isolation
Each test is isolated and doesn't depend on others. Tests can be run in any order.

### 2. Mocking
External dependencies are mocked to ensure tests are deterministic and fast.

### 3. Edge Cases
Tests cover both normal usage and edge cases, including:
- Invalid input handling
- Empty or malformed source code
- Interactive environment limitations
- Threading scenarios

### 4. Compatibility
Tests work with both `pdb` and `ipdb` debuggers, adapting to available tools.

### 5. Error Handling
Tests verify that errors are handled gracefully and don't crash the system.

## Test Patterns

### AST Testing Pattern
```python
def test_ast_functionality(self):
    source = """
    def example_function():
        return 42
    """
    tree = ast.parse(source)
    transformer = SomeTransformer()
    result = transformer.visit(tree)
    # Verify transformation
    assert result is not None
```

### Debugger Testing Pattern
```python
@patch('hot_restart.some_dependency')
def test_debugger_functionality(self, mock_dep):
    debugger = HotRestartPdb()
    # Test debugger behavior
    assert hasattr(debugger, 'expected_method')
```

### Integration Testing Pattern
```python
def test_real_world_usage(self):
    @hot_restart.wrap
    def test_function():
        return "test"
    
    result = test_function()
    assert result == "test"
    assert hasattr(test_function, '_hot_restart_already_wrapped')
```

## Common Issues and Solutions

### 1. Interactive Environment Limitations
Some tests may fail in interactive environments (REPL, Jupyter) because source code inspection doesn't work the same way. These failures are expected and handled gracefully.

### 2. Debugger Availability
Tests adapt to available debuggers. If `ipdb` is not available, tests fall back to `pdb`.

### 3. Threading Issues
Thread-local variables are tested carefully to ensure proper isolation between tests.

### 4. Temporary Files
Tests clean up temporary files automatically, but some may persist if tests are interrupted.

## Contributing

When adding new tests:

1. **Follow the existing patterns** - Use the same structure and naming conventions
2. **Test both success and failure cases** - Include edge cases and error conditions
3. **Mock external dependencies** - Keep tests fast and deterministic
4. **Document complex tests** - Add docstrings explaining what's being tested
5. **Run the full test suite** - Ensure new tests don't break existing functionality

### Adding New Test Files

1. Create the test file in the `tests/` directory
2. Follow the naming convention `test_*.py`
3. Import necessary modules and classes
4. Use descriptive test class and method names
5. Add comprehensive docstrings

### Test Naming Convention

- Test files: `test_<component>.py`
- Test classes: `Test<ComponentName>`
- Test methods: `test_<specific_functionality>`

## Environment Setup

Tests require the development environment to be set up:

```bash
# Install development dependencies
just install-dev

# Run tests
just test
```

## Debugging Tests

To debug a failing test:

```bash
# Run with verbose output
pytest tests/test_file.py::test_method -v -s

# Run with pdb on failure
pytest tests/test_file.py::test_method --pdb

# Run with coverage
pytest tests/ --cov=hot_restart --cov-report=html
```

## Test Performance

The test suite is designed to be fast:
- Unit tests complete in milliseconds
- Integration tests complete in seconds
- Full test suite completes in under 30 seconds

Performance is maintained through:
- Extensive mocking of slow operations
- Minimal file I/O
- Efficient test setup and teardown
- Parallel test execution where possible