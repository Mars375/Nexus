"""Maximum lengths of event fields, shared by the HTTP model and the service (#42).

The API model (`api.EventIn`) and `service.publish` both import these, so a direct call by an
adapter cannot store what the API would refuse.
"""

from datetime import timedelta

EVENT_ID_MAX = 128  # actor_event_id column
RUN_MAX = 128  # run_ref column; also the limit of payload.run_ref (rules.validate)
ANSWER_ID_PREFIX = "answer-"  # event ids reserved to Nexus: the response event of an approval
SUBJECT_MAX = 500
EVIDENCE_REF_MAX = 512  # measured after stripping whitespace, as the API does
CONSEQUENCE_MAX = 1000  # payload.consequence of a question / needs_human, measured raw (#26)
EXPIRY_MIN = timedelta(minutes=1)  # payload.expires_at: at least this long after reception
EXPIRY_MAX = timedelta(days=30)  # ... and at most this long (an exact duration, in UTC)
