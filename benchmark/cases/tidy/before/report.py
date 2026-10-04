def describe(rows):
    """One line per row, in the order the rows were given."""
    lines = []
    for row in rows:
        lines.append(f"{row['name']}: {row['count']}")
    return "\n".join(lines)
