def describe(rows):
    """One line per row, in the order the rows were given."""
    return "\n".join(f"{row['name']}: {row['count']}" for row in rows)
