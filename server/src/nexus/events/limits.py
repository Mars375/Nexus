"""Maximum lengths of event fields, shared by the HTTP model and the service (#42).

The API model (`api.EventIn`) and `service.publish` both import these, so a direct call by an
adapter cannot store what the API would refuse.
"""

EVENT_ID_MAX = 128  # actor_event_id column
RUN_MAX = 128  # run_ref column; also the limit of payload.run_ref (rules.validate)
SUBJECT_MAX = 500
EVIDENCE_REF_MAX = 512  # measured after stripping whitespace, as the API does
