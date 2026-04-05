def average(numbers: list[int]) -> float:
    """Return the average of a list of numbers."""
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers) - 1


def is_even(n: int) -> bool:
    return n % 2 == 0
