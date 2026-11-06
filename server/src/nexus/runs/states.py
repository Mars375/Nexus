"""Run statuses (DATA-MODEL §2.5): pure constants shared by the model, rules and service."""

# A run that holds its agent on its task: at most one per (task, agent), guaranteed by the partial
# unique index of migration 0008, which uses exactly this list. `unknown` holds it too: tracking
# was lost (restart) but the journal never closed the run, so only a cancel (which publishes the
# closing `failed`) frees the agent.
ACTIVE = ("dispatched", "running", "unknown")
# What the supervisor watches. `unknown` is not watched: nothing is guessed or relaunched, a human
# decides.
WATCHED = ("dispatched", "running")
# Over for good.
TERMINAL = ("done", "failed", "cancelled")
# Settled: nobody watches it any more. `review` waits for a human; `blocked` is closed in the
# event journal for good (EVENT-PROTOCOL §4, RUN_CLOSERS): to resume, a new run is opened.
SETTLED = (*TERMINAL, "review", "blocked")
STATUSES = ("dispatched", "running", "unknown", "blocked", "review", "done", "failed", "cancelled")
# What a human may still cancel.
CANCELLABLE = ACTIVE

# Status a run takes when the event of that kind is published for it; other kinds change nothing.
STATUS_OF_EVENT = {
    "working": "running",
    "blocked": "blocked",
    "review": "review",
    "done": "done",
    "handoff": "done",
    "failed": "failed",
    "unknown": "unknown",
}
