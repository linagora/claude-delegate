class Pricing:
    """A price list that answers by name and remembers what it answered."""

    def __init__(self, rates):
        self.rates = rates
        self._cache = {}

    def price(self, name):
        if name not in self._cache:
            self._cache[name] = self.rates[name] * 1.2
        return self._cache[name]

    def set_rate(self, name, value):
        self.rates[name] = value
