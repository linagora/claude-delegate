from __future__ import annotations

#: Exit codes, one per class of failure (2 is argparse's usage error and 1 is
#: left to unexpected crashes).
EXIT_PREPARATION = 3  #: the review could not be prepared; the reviewer was not called
EXIT_QUOTA = 4  #: the Claude usage limit is reached
EXIT_INCOMPLETE = 5  #: the review hit its budget or turn limit
EXIT_INVALID_OUTPUT = 6  #: the structured output is missing or off-schema
EXIT_DELEGATE = 7  #: any other failure of the delegated session


class DelegateError(Exception):
    """A failure reported to the user on stderr, with a dedicated exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_DELEGATE) -> None:
        super().__init__(message)
        self.exit_code = exit_code
