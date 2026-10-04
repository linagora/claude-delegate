from dataclasses import dataclass


@dataclass(eq=False)
class Usage:
    """A counter that several threads increment."""

    total: int = 0

    def add(self, cost):
        self.total += cost
        return self.total
