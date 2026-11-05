"""The reserved `nx-run-` prefix (ADR-023, D2): such a run reference must name a real run.

Nexus mints `nx-run-<n>` references; an event that cites one must belong to the same task and be
signed by the run's executor (`runs.executor`), otherwise anyone could write into another run's
story. Any other run name stays a free label, as before.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from nexus.events.rules import Envelope
from nexus.models import Run, Task
from nexus.tasks.rules import RuleViolation

RESERVED_PREFIX = "nx-run-"
# Canonical spelling only (no leading zero): one run, one reference, or closers could not match.
_REF = re.compile(r"nx-run-([1-9][0-9]{0,11})")


def check_run_refs(session: Session, envelope: Envelope, task: Task | None) -> None:
    """409 `run_unknown` when `run` or `payload.run_ref` uses the reserved prefix wrongly.

    The prefix is matched case-insensitively and after stripping, so no spelling escapes it. The
    message never repeats the received value.
    """
    for candidate in (envelope.run, envelope.payload.get("run_ref")):
        if not isinstance(candidate, str):
            continue
        name = candidate.strip()
        if not name.casefold().startswith(RESERVED_PREFIX):
            continue
        match = _REF.fullmatch(name)
        run = session.get(Run, int(match.group(1))) if match else None
        if run is None or task is None or run.task_id != task.id or run.executor != envelope.actor:
            raise RuleViolation(
                "run_unknown",
                "le préfixe « nx-run- » est réservé à Nexus : cette référence ne désigne pas un "
                "run de cette tâche confié à cet exécutant",
            )
