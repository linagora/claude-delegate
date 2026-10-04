DEFAULT_SIZE = 20


def page(items, number, size=DEFAULT_SIZE):
    start = number * size
    return items[start:start + size]


def last_page_number(items, size=DEFAULT_SIZE):
    return (len(items) - 1) // size
