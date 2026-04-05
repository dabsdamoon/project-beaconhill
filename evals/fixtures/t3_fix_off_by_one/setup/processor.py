def get_last_n(items: list, n: int) -> list:
    """Return the last n items from the list."""
    return items[len(items) - n - 1:]


def chunk_list(items: list, size: int) -> list[list]:
    """Split a list into chunks of the given size."""
    return [items[i:i + size] for i in range(0, len(items), size)]
