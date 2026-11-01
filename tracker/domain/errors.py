# Errors the user caused and should be told about. The website shows them as a
# toast or form error, the CLI prints them, so the core doesn't care who called it.


class CoopTrackError(Exception):
    pass


class NotFound(CoopTrackError):
    pass


class InvalidMove(CoopTrackError):
    pass


class NothingToUndo(CoopTrackError):
    pass


class JobSearchError(CoopTrackError):
    pass
