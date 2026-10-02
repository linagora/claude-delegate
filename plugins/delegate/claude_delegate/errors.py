from __future__ import annotations

#: The review could not be prepared (git or forge); the reviewer was not called.
EXIT_PREPARATION = 3


class DelegateError(Exception):
    """A failure reported to the user on stderr, with a dedicated exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code
