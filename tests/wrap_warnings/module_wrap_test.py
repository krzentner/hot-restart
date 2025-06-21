import hot_restart


def main():
    # Lambda function - won't have source
    my_lambda = lambda x: x + 1

    # Built-in function reference
    my_builtin = print

    # Regular function that can be wrapped
    def regular_function():
        return "This function has source"

    # Another regular function
    def another_function():
        return "Another function with source"

    # Class with methods
    class MyClass:
        # Lambda as class attribute
        class_lambda = lambda self, x: x * 2

        def regular_method(self):
            return "Regular method"

        # Built-in reference as attribute
        builtin_ref = len

    # This will wrap the entire module
    hot_restart.wrap_module()

    # Test that everything still works
    print("Lambda result:", my_lambda(5))
    print("Regular function:", regular_function())
    print("Class method:", MyClass().regular_method())


if __name__ == "__main__":
    main()
