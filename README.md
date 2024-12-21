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

Call `hot_restart.wrap_module()` at the end of a module where you expect
functions to crash:

```python
import hot_restart

def my_func():
    ...

class MyClass:

    def forward(self, x):
        super().forward(x * 2)

# Must be called after definitions
hot_restart.wrap_module()
```


The above is equivalent to wrapping each function and class defined in the module:

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

When a wrapped function crashes (by default, throws any exception besides
`StopIteration`), hot_restart will open a post mortem debugger in the wrapped
function, with the rest of the stack still live above that function call.

Then you can modify the source code of your crashing function, and (c)ontinue
from the debugger, and hot_restart will reload the source of that function (and
only that function).

You can use `@hot_restart.no_wrap` to indicate that a function or class should
not be wrapped.

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

### Line numbers and Surrogate Sources
`hot_restart` generates a surrogate source file to compile.
This avoids import-time side effects on reload, but means that line numbers may
become slightly different than the source on disk.
When using pdb, by default the source of the reloaded file will be set to the
surrogate source file, ensuring that line numbers in pdb match the executed
code. In other debuggers (or when
`hot_restart.DEBUG_ORIGINAL_PATH_RELOADED_CODE` is True), the original source
will be used.

### `super()` Calls

hot_restart rewrites `super()` into `super(<classname>, <first argument>)` in
reloaded source (original source is loaded intact). This prevents methods from
acquiring a closure variable `__class__`, which would break in many cases, but
slightly changes lookup behavior if the class is redefined.

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
If you're looking for a more maximalist implementation of this workflow with
IDE integration, you may be interested in
[Reloadium](https://github.com/reloadware/reloadium).

Although these useful alternatives exist, I created `hot_restart` because
I found it difficult to debug failures in those systems.
`hot_restart` intentionally implements a more minimal set of reloading routines
that I can easily wrap my head around.
