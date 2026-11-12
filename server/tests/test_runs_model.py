"""The model of a run (ADR-023 addendum, lot H1): required for Claude, refused elsewhere."""

import pytest
from runs_support import FakeAdapter, code_of, dispatch, make_task, register, tick

from nexus.adapters.base import RunInfo
from nexus.models import Run
from nexus.runs import rules, supervisor


def test_the_closed_list_and_its_executors():
    assert rules.RUN_MODELS == ("haiku", "sonnet", "opus")
    assert rules.MODELS_OF == {"claude": rules.RUN_MODELS}


def test_check_model_is_pure():
    rules.check_model("claude", "opus")
    rules.check_model("codex", None)
    with pytest.raises(rules.RuleViolation) as missing:
        rules.check_model("claude", None)
    assert missing.value.code == "model_required"
    with pytest.raises(rules.RuleViolation) as extra:
        rules.check_model("codex", "opus")
    assert extra.value.code == "model_not_for_executor"


def test_claude_without_a_model_is_a_409(client):
    register(client, "claude")
    task = make_task(client)

    res = dispatch(client, task, executor="claude", agent="claude")

    assert (res.status_code, code_of(res)) == (409, "model_required")
    assert client.get(f"/api/tasks/{task}/runs").json() == []


@pytest.mark.parametrize(
    ("executor", "agent"), [("codex", "codex"), ("hermes", "helios"), ("orca", "orca")]
)
def test_an_executor_without_models_refuses_one(client, executor, agent):
    register(client, executor)
    task = make_task(client)

    res = dispatch(client, task, executor=executor, agent=agent, model="sonnet")

    assert (res.status_code, code_of(res)) == (409, "model_not_for_executor")


def test_no_adapter_is_still_the_most_useful_answer(client):
    task = make_task(client)
    res = dispatch(client, task, executor="claude", agent="claude")
    assert (res.status_code, code_of(res)) == (409, "executor_unavailable")


def test_the_model_is_checked_before_the_task_is_ready(client):
    register(client, "claude")
    task = make_task(client, next_action=None)
    res = dispatch(client, task, executor="claude", agent="claude")
    assert code_of(res) == "model_required"


def test_an_unknown_model_is_a_422_that_never_echoes_it(client):
    register(client, "claude")
    task = make_task(client)
    secret = "ghp_" + "A" * 36

    for value in ("fable", secret):
        res = dispatch(client, task, executor="claude", agent="claude", model=value)
        assert res.status_code == 422
        assert value not in res.text


def test_a_claude_run_stores_and_returns_its_model(client):
    register(client, "claude")
    task = make_task(client)

    res = dispatch(client, task, executor="claude", agent="claude", model="opus")

    assert res.status_code == 201 and res.json()["model"] == "opus"
    assert client.get("/api/runs/nx-run-1").json()["model"] == "opus"
    assert client.get(f"/api/tasks/{task}/runs").json()[0]["model"] == "opus"


def test_a_run_without_models_reads_null(client):
    register(client)
    task = make_task(client)
    assert dispatch(client, task).json()["model"] is None


def test_same_key_same_model_is_a_readback_another_model_is_refused(client):
    register(client, "claude")
    task = make_task(client)
    kw = {"executor": "claude", "agent": "claude"}

    first = dispatch(client, task, model="sonnet", **kw)
    again = dispatch(client, task, model="sonnet", **kw)
    other = dispatch(client, task, model="haiku", **kw)

    assert (first.status_code, again.status_code) == (201, 200)
    assert (other.status_code, code_of(other)) == (409, "client_key_reused")


def test_executors_serve_their_models(client):
    register(client)
    register(client, "claude")
    got = {e["executor"]: e["models"] for e in client.get("/api/executors").json()}
    assert got == {"codex": [], "claude": ["haiku", "sonnet", "opus"]}


def test_an_adapter_can_narrow_the_models(client):
    adapter = FakeAdapter()
    adapter.models = ("haiku",)
    register(client, "claude", adapter)
    [one] = client.get("/api/executors").json()
    assert one["models"] == ["haiku"]


class Capturing(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.infos: list[RunInfo] = []

    def dispatch(self, run):
        self.infos.append(run)
        return super().dispatch(run)


def test_the_supervisor_hands_the_model_to_the_adapter(client):
    adapter = Capturing()
    register(client, "claude", adapter)
    dispatch(client, make_task(client), executor="claude", agent="claude", model="haiku")

    tick(client)

    assert [i.model for i in adapter.infos] == ["haiku"]


def test_info_of_defaults_to_no_model():
    run = Run(id=1, task_id=1, executor="codex", agent="codex", dispatched_by="loic",
              client_key="k", brief="b", status="dispatched", version=1)
    assert supervisor.info_of(run).model is None


def test_a_model_the_adapter_does_not_serve_is_a_409(client):
    adapter = FakeAdapter()
    adapter.models = ("haiku",)
    register(client, "claude", adapter)
    task = make_task(client)
    kw = {"executor": "claude", "agent": "claude"}

    refused = dispatch(client, task, model="sonnet", **kw)
    created = dispatch(client, task, model="haiku", client_key="k2", **kw)

    assert (refused.status_code, code_of(refused)) == (409, "model_unavailable")
    assert created.status_code == 201 and created.json()["model"] == "haiku"
