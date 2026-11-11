"""Proofs of a Hermes completion (spec §4.4): attachments Hermes copied, found on the disk.

DONE is not a proof: only a file Hermes itself recorded when the task ended (`kanban_complete`)
or went to review (`kanban_request_review`) counts, and only if it is still there with the size
Hermes noted. One `stat`, never a read of the content.
"""

from __future__ import annotations

import os
from typing import Any

COPIED_BY = frozenset({"kanban_complete", "kanban_request_review"})
PATH_MAX = 400
PROOFS_MAX = 10


def _local_absolute(path: object) -> bool:
    if not isinstance(path, str) or not path or len(path) > PATH_MAX:
        return False
    if path.startswith(("\\\\", "//")):  # UNC, `\\?\` and `\\.\` forms
        return False
    return os.path.isabs(path)


def _is_proof(item: Any) -> bool:
    if not isinstance(item, dict) or item.get("uploaded_by") not in COPIED_BY:
        return False
    path, size = item.get("stored_path"), item.get("size")
    if not _local_absolute(path) or not isinstance(size, int) or isinstance(size, bool):
        return False
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return False
    return os.path.isfile(path) and info.st_size == size


def proofs_from(attachments: object) -> list[str]:
    """`file:<path>` for each attachment that qualifies (at most `PROOFS_MAX`)."""
    if not isinstance(attachments, list):
        return []
    found = [f"file:{a['stored_path']}" for a in attachments if _is_proof(a)]
    return found[:PROOFS_MAX]
