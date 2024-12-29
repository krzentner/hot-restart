import hot_restart

@hot_restart.wrap
def outer_fn():

    @hot_restart.wrap
    def inner_fn():
        print('hi')

    inner_fn()

outer_fn()
