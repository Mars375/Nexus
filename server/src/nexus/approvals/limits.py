"""Bounds of the approvals read API, shared by the HTTP layer and the service."""

LIST_LIMIT_DEFAULT = 200
LIST_LIMIT_MAX = 1000
REF_PREFIX = "nx-appr-"
REF_DIGITS_MAX = 12  # same bound as the other references
ANSWER_TEXT_MAX = 2000  # the text of an answer, measured after stripping (as the API does)
NOTE_MAX = 2000  # the optional note of a decision, same measure
