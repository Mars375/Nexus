"""Run statuses (DATA-MODEL §2.5): pure constants shared by the model, rules and service."""

# A live run: its executor is working or may be, and the supervisor watches it. At most one per
# (task, agent): the partial unique index of migration 0008 uses exactly this list.
ACTIVE = ("dispatched", "running", "blocked")
# Over for good.
TERMINAL = ("done", "failed", "cancelled")
# `review`: the executor stopped and waits for a human, nobody watches it any more.
SETTLED = (*TERMINAL, "review")
# `unknown`: tracking was lost (restart); nothing is relaunched on its own, a human decides.
STATUSES = (*ACTIVE, "review", "done", "failed", "cancelled", "unknown")
# What a human may still cancel.
CANCELLABLE = (*ACTIVE, "unknown")

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
