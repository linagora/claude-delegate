import threading


class Usage:
    """A counter that several threads increment."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total = 0

    def add(self, cost):
        with self._lock:
            self.total += cost
        return self.total
