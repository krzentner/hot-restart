"""Test module for wrap_modules - module with no_wrap decorators"""

import hot_restart


@hot_restart.no_wrap
def no_wrap_func():
    return "no_wrap"


def regular_func():
    return "regular"


@hot_restart.no_wrap
class NoWrapClass:
    def method(self):
        return "no_wrap_method"


class RegularClass:
    def method(self):
        return "regular_method"
