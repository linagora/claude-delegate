from dataclasses import dataclass, field


@dataclass
class Usage:
    """A counter that several threads increment."""

    total: float = field(default=0.0)

    def add(self, cost):
        self.total += cost
        return self.total
