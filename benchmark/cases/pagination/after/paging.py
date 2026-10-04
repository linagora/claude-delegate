DEFAULT_SIZE = 20


def page(items, number, size=DEFAULT_SIZE):
    start = number * size
    end = start + size
    # A page that runs past the end keeps the items that are left.
    if not items:
        return []
    end = min(end, len(items))
    return items[start:end]


def last_page_number(items, size=DEFAULT_SIZE):
    return (len(items) - 1) // size
