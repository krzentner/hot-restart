Restart debugging your program in the function that failed.

Minimal hot-reload-and-restart library.

## Usage:

Wrap any function you expect to crash in `@hot_restart.wrap`:

```python
import hot_restart

@hot_restart.wrap
def my_func():
    ...

@hot_restart.wrap_class
class MyClass:

    def forward(self, x):
        super().forward(x * 2)
```

Alternatively, call `hot_restart.wrap_module()` after your functions and
classes are defined.

When a wrapped function crashes, hot_restart will open a post mortem debugger
in the wrapped function, with the rest of the stack still live above that
function call.

Then you can modify the source code of your crashing function, and (c)ontinue
from the debugger, and hot_restart will reload the source of that function (and
only that function).


## Edge Cases

You can also trigger a full module reload with `hot_restart.reload_module()`,
although that may result in duplicate (i.e. conflicting) class defintions.

hot_restart uses source re-writing to handle the common cases, and does not
patch the byte-code of functions.

### `super()` Calls

hot_restart rewrites `super()` into `super(type(self, self)` in reloaded source
(original source is loaded intact). This prevents methods from acquiring a
closure variable `__class__`, which would break in many cases, but this
re-write can fail if `self` is not defined where `super()` is used. This
restriction may be removed in the future.

To work around this, you can use the two-argument form of `super()` manually.

### Closures and Nested Functions

hot_restart will patch in old closure variables into newly defined functions,
as long as `hot_restart.wrap` is the innermost decorator.
However, functions cannot add new closure variables without a full module
reload. Functions can still gain new arguments.

For nested functions, `hot_restart.wrap_module()` cannot find the inner
function, so `hot_restart.wrap()` must be used manually.

If `hot_restart.wrap` is not the inner most decorator, then closure variables
will be lost.
