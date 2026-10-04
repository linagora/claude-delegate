def _normalise(text):
    return text.strip().lower()


def slugify(text):
    return _normalise(text).replace(" ", "-")
