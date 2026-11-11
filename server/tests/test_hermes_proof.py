"""Proofs of a completion: attachments copied by Hermes and present on disk (spec §4.4)."""

from datetime import UTC, datetime

from hermes_support import T0, TASK_ID, attachment, event, run_row, show_payload

from nexus.adapters import hermes_proof
from nexus.adapters.hermes_translate import translate

NOW = datetime.fromtimestamp(T0 + 60, UTC)


def make_file(tmp_path, name="rapport.md", content="cinq lignes"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_a_copied_attachment_that_exists_is_a_proof(tmp_path):
    f = make_file(tmp_path)
    size = f.stat().st_size
    assert hermes_proof.proofs_from([attachment(f, size)]) == [f"file:{f}"]
    assert hermes_proof.proofs_from([attachment(f, size, "kanban_request_review")]) == [f"file:{f}"]


def test_everything_else_is_refused(tmp_path):
    f = make_file(tmp_path)
    size = f.stat().st_size
    items = [
        attachment(tmp_path / "absent.md", 3),
        attachment(f, size + 1),
        attachment(f, size, "attach"),
        attachment("relatif/rapport.md", size),
        attachment("\\\\serveur\\partage\\rapport.md", size),
        attachment("\\\\?\\" + str(f), size),
        attachment(tmp_path / ("a" * 401), 1),
        attachment(tmp_path, 0),  # a directory
        {"uploaded_by": "kanban_complete", "stored_path": 3, "size": "x"},
        "pas un dict",
    ]
    assert hermes_proof.proofs_from(items) == []


def test_at_most_ten_proofs(tmp_path):
    items = []
    for i in range(12):
        f = make_file(tmp_path, f"f{i}.md")
        items.append(attachment(f, f.stat().st_size))
    assert len(hermes_proof.proofs_from(items)) == 10


def test_artifacts_in_metadata_are_not_proofs_and_a_commit_is_cut():
    meta = {"artifacts": ["C:/scratch/x.md"], "changed_files": ["a.py"], "tests_run": 3,
            "commit": "a1b2c3d4e5f6" + "0" * 28}
    show = show_payload("done", events=[event("completed", T0 + 5, None, 1)],
                        runs=[run_row(1, "completed", "ok", meta)])
    end = translate(show, 0, proofs=[], now=NOW, max_seconds=3600).events[-1]
    assert end.kind == "review" and end.evidence == [f"hermes:nexus/{TASK_ID}"]
    assert end.payload["commit"] == "a1b2c3d4e5f6" and end.payload["tests_run"] == 3
    assert end.payload["changed_files"] == ["a.py"]
