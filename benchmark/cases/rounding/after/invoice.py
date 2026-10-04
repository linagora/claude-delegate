def total_cents(items):
    """The sum of the line amounts, in cents."""
    return sum(round(item["amount"] * 100) for item in items)
