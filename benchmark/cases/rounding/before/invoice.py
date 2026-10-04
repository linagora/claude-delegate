def total_cents(items):
    """The sum of the line amounts, in cents."""
    return round(sum(item["amount"] for item in items) * 100)
