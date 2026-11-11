class EmuError(Exception):
    """A problem the user can act on; reported without a traceback."""

    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint
