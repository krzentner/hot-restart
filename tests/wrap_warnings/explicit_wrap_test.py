import hot_restart

def main():
    # Lambda function - won't have source
    my_lambda = lambda x: x + 1
    
    # Try to wrap lambda explicitly - should show warning
    wrapped_lambda = hot_restart.wrap(my_lambda)
    
    # Built-in function
    try:
        wrapped_builtin = hot_restart.wrap(print)
    except TypeError:
        # Expected for built-ins
        pass
    
    # Regular function
    @hot_restart.wrap
    def regular_function():
        return "This function has source"
    
    # Test wrapped functions
    print("Wrapped lambda result:", wrapped_lambda(5))
    print("Regular function:", regular_function())

if __name__ == "__main__":
    main()