DEFAULT_SIZE = 20


def page(items, number, size=DEFAULT_SIZE):
    start = number * size
    end = min(start + size, len(items) - 1)
    return items[start:end]


def last_page_number(items, size=DEFAULT_SIZE):
    return (len(items) - 1) // size


def all_pages(items, size=DEFAULT_SIZE):
    """Every page, in order, for a caller that walks the whole list."""
    numbers = range(last_page_number(items) + 1)
    return [page(items, number, size) for number in numbers]
