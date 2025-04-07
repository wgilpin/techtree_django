"""Constants used throughout the application."""

# Difficulty levels with their display names and numeric values
DIFFICULTY_BEGINNER = "Beginner"
DIFFICULTY_EARLY_LEARNER = "Early Learner"
DIFFICULTY_GOOD_KNOWLEDGE = "Good Knowledge"
DIFFICULTY_ADVANCED = "Advanced"

# Ordered list of difficulty levels from easiest to hardest
DIFFICULTY_LEVELS = [
    DIFFICULTY_BEGINNER,
    DIFFICULTY_EARLY_LEARNER,
    DIFFICULTY_GOOD_KNOWLEDGE,
    DIFFICULTY_ADVANCED
]

# Mapping of difficulty levels to numeric values
DIFFICULTY_VALUES = {
    DIFFICULTY_BEGINNER: 0,
    DIFFICULTY_EARLY_LEARNER: 1,
    DIFFICULTY_GOOD_KNOWLEDGE: 2,
    DIFFICULTY_ADVANCED: 3
}

# Reverse mapping from numeric values to difficulty levels
DIFFICULTY_FROM_VALUE = {v: k for k, v in DIFFICULTY_VALUES.items()}


# Mapping from lowercase key to display value
DIFFICULTY_KEY_TO_DISPLAY = {
    level.lower(): level for level in DIFFICULTY_LEVELS
}

# Function to get the next lower difficulty level
def get_lower_difficulty(current_level):
    """
    Returns the next lower difficulty level, or None if already at lowest.

    Args:
        current_level (str): The current difficulty level

    Returns:
        str or None: The next lower difficulty level, or None if already at lowest
    """
    try:
        current_index = DIFFICULTY_LEVELS.index(current_level)
        if current_index > 0:
            return DIFFICULTY_LEVELS[current_index - 1]
        return None
    except ValueError:
        return None