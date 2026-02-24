from numpy import random

def roll_dice(num_dice=1, num_sides=6):
    if num_dice < 1 or num_sides < 2:
        raise ValueError("Number of dice must be at least 1 and number of sides must be at least 2.")
    
    rolls = random.randint(1, num_sides + 1, size=num_dice).tolist()
    return rolls
