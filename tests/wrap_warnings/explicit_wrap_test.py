import hot_restart


def main():
    # Lambda function - won't have source
    my_lambda = lambda x: x + 1

    # Try to wrap lambda explicitly - should raise ReloadException
    try:
        wrapped_lambda = hot_restart.wrap(my_lambda)
        # If it somehow succeeds, test it
        print("Wrapped lambda result:", wrapped_lambda(5))
    except hot_restart.ReloadException as e:
        print(f"Lambda wrap failed with ReloadException: {e}")

    # Built-in function
    try:
        wrapped_builtin = hot_restart.wrap(print)
    except (TypeError, hot_restart.ReloadException) as e:
        # Expected for built-ins
        print(f"Builtin wrap failed: {type(e).__name__}")

    # Regular function
    @hot_restart.wrap
    def regular_function():
        return "This function has source"

    # Test wrapped functions
    print("Regular function:", regular_function())


if __name__ == "__main__":
    main()
