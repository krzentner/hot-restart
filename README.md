# `hot_restart`

Restart debugging your program in the function that failed.

Installation:
```
pip install hot_restart
```

`hot_restart` currently has no required dependencies outside the standard library.
If `pydevd` is already imported, `hot_restart` will use it to allow debugging
in VS Code (and other IDEs using `pydevd` / `debugpy`).

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

`hot_restart` uses AST transformations to find new definitions, to avoid
causing "import-time" side effects, and to match line numbers with the real
source code while keeping each version of a function (except the initial load)
in its own source file.

## Edge Cases

You can also trigger a full module reload with `hot_restart.reload_module()`.
This may trigger "import-time" side effects and duplicate (i.e. conflicting)
class definitions. To avoid restarting your main function when reloading your
main module, check `hot_restart.is_restarting_module()`.

`hot_restart` uses source re-writing to handle the common cases, and does not
patch the byte-code of functions.
This limits `hot_restart` from handling adding new variables to a closure or
adding methods to existing class instances, but simplifies the implementation.

### `super()` Calls

hot_restart rewrites `super()` into `super(type(self, self)` in reloaded source
(original source is loaded intact). This prevents methods from acquiring a
closure variable `__class__`, which would break in many cases, but this
re-write can fail if `self` is not defined where `super()` is used. This
restriction may be removed in the future.

To work around this, you can use the two-argument form of `super()` manually.

### Closures and Nested Functions

`hot_restart` will patch in old closure variables into newly defined functions,
as long as `hot_restart.wrap` is the innermost decorator. However, functions
cannot add new closure variables without a full module reload. Functions can
still gain new arguments.

For nested functions, `hot_restart.wrap_module()` cannot find the inner
function, so `hot_restart.wrap()` must be used manually.

If `hot_restart.wrap` is not the inner-most decorator, then closure variables
will be lost.


## Alternative / Complementary Tools:

If you just want more complete hot reloading (for example, the ability to add
new methods to existing instances of classes), you should consider
[jurigged](https://github.com/breuleux/jurigged). You should also be able to
use `jurigged` with `hot_restart`. If you want to use `jurigged`'s code
reloading with `hot_restart`'s function restarting, you can disable
`hot_restart`'s automatic code reloading by setting:

```
hot_restart.RELOAD_ON_CONTINUE = False
```

This module implements a workflow similar to "edit-and-continue".
If you're looking for a more maximalist implementation of this workflow with IDE integration, you may be interested in [Reloadium](https://reloadium.io/).

Although these useful alternatives exist, I created `hot_restart` because
I found it difficult to debug failures in those systems.
`hot_restart` intentionally implements a more minimal set of reloading routines
that I can easily wrap my head around.
