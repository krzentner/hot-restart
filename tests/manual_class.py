#!/usr/bin/env python3
"""
Demonstration of hot-restart's class reloading with identity preservation.

This script shows how classes can be reloaded with new methods while:
1. Preserving isinstance() checks
2. Maintaining Python's method resolution order (MRO)
3. Allowing existing instances to access new methods

Usage:
1. Run this script: python demo_class_reload.py
2. When it crashes, edit this file and uncomment the new_method() 
3. Type 'c' in the debugger to continue
4. The script will reload and demonstrate that isinstance checks still work
"""

import hot_restart

# Enable reload on continue
hot_restart.RELOAD_ALL_ON_CONTINUE = True


@hot_restart.wrap
class Animal:
    def __init__(self, name):
        self.name = name
    
    def speak(self):
        return f"{self.name} makes a sound"
    
    # Uncomment this method after the first crash:
    # def describe(self):
    #     return f"This is {self.name}"


@hot_restart.wrap
class Dog(Animal):
    def speak(self):
        return f"{self.name} barks!"
    
    # Uncomment this method after the first crash:
    # def fetch(self):
    #     return f"{self.name} fetches the ball"


@hot_restart.wrap
def main():
    # Create instances before any reload
    generic_animal = Animal("Generic")
    my_dog = Dog("Buddy")
    
    # Store original class IDs for comparison
    animal_id = id(Animal)
    dog_id = id(Dog)
    
    print("=== Before Reload ===")
    print(f"Animal.speak(): {generic_animal.speak()}")
    print(f"Dog.speak(): {my_dog.speak()}")
    print(f"isinstance(my_dog, Dog): {isinstance(my_dog, Dog)}")
    print(f"isinstance(my_dog, Animal): {isinstance(my_dog, Animal)}")
    print(f"type(my_dog) is Dog: {type(my_dog) is Dog}")
    print(f"Animal class ID: {animal_id}")
    print(f"Dog class ID: {dog_id}")
    print(f"MRO: {[cls.__name__ for cls in Dog.__mro__]}")
    
    # Check if new methods exist (they won't initially)
    has_describe = hasattr(generic_animal, 'describe')
    has_fetch = hasattr(my_dog, 'fetch')
    print(f"\nHas describe method: {has_describe}")
    print(f"Has fetch method: {has_fetch}")
    
    if not has_describe:
        print("\n>>> Now edit this file and uncomment the new methods, then continue <<<")
        raise ValueError("Trigger reload - uncomment new methods and continue!")
    
    # After reload, the same instances should have new methods
    print("\n=== After Reload ===")
    print(f"Animal.speak(): {generic_animal.speak()}")
    print(f"Dog.speak(): {my_dog.speak()}")
    
    # New methods should work on existing instances
    print(f"Animal.describe(): {generic_animal.describe()}")
    print(f"Dog.fetch(): {my_dog.fetch()}")
    
    # isinstance checks should still work
    print(f"\ninstanceof checks still work:")
    print(f"isinstance(my_dog, Dog): {isinstance(my_dog, Dog)}")
    print(f"isinstance(my_dog, Animal): {isinstance(my_dog, Animal)}")
    print(f"type(my_dog) is Dog: {type(my_dog) is Dog}")
    
    # Class IDs should be the same (identity preserved)
    print(f"\nClass identity preserved:")
    print(f"Animal class ID: {id(Animal)} (same: {id(Animal) == animal_id})")
    print(f"Dog class ID: {id(Dog)} (same: {id(Dog) == dog_id})")
    
    # MRO should be maintained
    print(f"MRO still intact: {[cls.__name__ for cls in Dog.__mro__]}")
    
    print("\n✅ Success! Classes reloaded with new methods while preserving identity!")


if __name__ == "__main__":
    main()