"""The watch of the Tailscale address: confirmation, closing and shutdown (ADR-021)."""

import http.client
import json
import logging
import subprocess
import threading

import pytest
import serving_support
from serving_support import (
    CONFIRM,
    GUARD,
    STOPPED,
    TAIL,
    TAIL6,
    Rounds,
    assert_accepts,
    assert_refuses,
    http_get,
    serving_warnings,
    status,
)

from nexus import nodes, serving

launch = serving_support.launch
records = serving_support.records


# --- check against Tailscale ------------------------------------------------------------------



UNCONFIRMED = [
    status(ips=("100.101.102.104",)),
    status(ips=()),
    json.dumps({"BackendState": "Running", "TailscaleIPs": None}),
    json.dumps({"BackendState": "Running"}),
    status(ips=("not-an-address",)),
    "not json at all",
    json.dumps({"BackendState": "Running", "TailscaleIPs": TAIL}),
    json.dumps([]),
    status("Stopped"),
    status("NeedsLogin"),
    status("Starting"),
]


@pytest.mark.parametrize("output", UNCONFIRMED)
def test_unconfirmed_outputs_never_bind(launch, records, output):
    run = launch(rounds=Rounds(), default=output)
    for index in range(3):
        run.rounds.next_end()
        if index < 2:
            run.rounds.go()
    assert run.bind.tail_count == 0
    assert len(serving_warnings(records)) == 1
    assert len([m for m in records.serving(level=logging.DEBUG) if "non confirmée" in m]) == 2
    assert TAIL not in records.text() and "BackendState" not in records.text()
    assert output not in records.text()
    assert http_get(run.port) == 200
    assert_refuses(run.tail_port)


FAILURES = [
    (FileNotFoundError("tailscale " + TAIL), nodes.NOT_FOUND),
    (PermissionError("denied " + TAIL), nodes.NOT_FOUND),
    (subprocess.CalledProcessError(1, "tailscale"), nodes.UNREADABLE),
    (subprocess.TimeoutExpired("tailscale", 5), nodes.NO_ANSWER),
    (TimeoutError("late " + TAIL), nodes.NO_ANSWER),
    (RuntimeError(TAIL + " secret"), f"{nodes.CHECK_FAILED} (RuntimeError)"),
]


@pytest.mark.parametrize("exc,reason", FAILURES)
def test_runner_failures_keep_watching(launch, records, exc, reason):
    run = launch(rounds=Rounds(), script=[exc])
    run.rounds.next_end()
    warnings = serving_warnings(records)
    assert len(warnings) == 1 and reason in warnings[0]
    assert TAIL not in records.text() and "secret" not in records.text()
    assert "Traceback" not in records.text()
    assert all(item[3] is None for item in records.items)  # no exc_info anywhere
    run.rounds.go()
    run.rounds.next_end()  # the task is still alive at round 2
    assert run.bind.tail_count == 1  # and the default (confirming) runner opened the listener


def test_ipv6_tailnet_address_is_confirmed(launch, records):
    spelled_out = '{"BackendState": "Running", "TailscaleIPs": ["fd7a:115c:a1e0:0:0:0:0:1"]}'
    run = launch(hosts=(TAIL6,), default=spelled_out, rounds=Rounds())
    run.rounds.next_end()
    assert run.bind.tail_count == 1
    assert records.wait_for("écoute du tailnet ouverte")
    assert_accepts(run.tail_port)


def test_a_served_tailnet_address_stays_bound_across_five_confirmed_rounds(launch, records):
    """D9: every round checks a served address, but a confirmation never rebinds it."""
    run = launch(rounds=Rounds())
    for index in range(5):
        run.rounds.next_end()  # round `index + 1` has checked the address
        if index < 4:
            run.rounds.go()
    assert run.runner.count == 5
    assert run.bind.tail_count == 1
    assert run.on_loop(lambda: run.tail.state) == serving.SERVED
    assert_accepts(run.tail_port)
    assert records.serving(level=logging.WARNING) == []


def test_a_served_tailnet_address_no_longer_confirmed_is_closed(launch, records):
    run = launch(rounds=Rounds(), script=[CONFIRM, STOPPED, CONFIRM])
    run.rounds.next_end()  # round 1: opened
    connection = http.client.HTTPConnection("127.0.0.1", run.tail_port, timeout=5)
    assert http_get(run.tail_port, conn=connection) == 200
    assert run.runner.count == 1 and run.bind.tail_count == 1
    mark = len(records.items)

    run.rounds.go()
    run.rounds.next_end()  # round 2: Stopped
    assert run.runner.count == 2  # one call in the round
    assert run.bind.tail_count == 1  # and no reopening in the same round
    assert run.on_loop(lambda: len(run.server.servers)) == 1  # loopback only
    assert_refuses(run.tail_port)
    assert http_get(run.tail_port, conn=connection) == 200  # the accepted connection goes on
    assert records.serving(mark, logging.WARNING) == [
        "écoute du tailnet fermée : adresse non confirmée par Tailscale (Tailscale pas connecté)"
    ]
    mark = len(records.items)

    run.rounds.go()
    run.rounds.next_end()  # round 3: confirmed again
    assert run.bind.tail_count == 2
    assert "écoute du tailnet reprise" in records.serving(mark, logging.INFO)
    assert_accepts(run.tail_port)
    connection.close()


def test_reason_changes_warn_once_each(launch, records):
    run = launch(
        rounds=Rounds(),
        script=[status("NeedsLogin"), status("NeedsLogin"), FileNotFoundError("x")],
    )
    for index in range(3):
        run.rounds.next_end()
        if index < 2:
            run.rounds.go()
    levels = [
        lvl for name, lvl, message, _ in records.items
        if name == "nexus.serving" and "non confirmée" in message
    ]
    assert levels == [logging.WARNING, logging.DEBUG, logging.WARNING]


def test_loopback_is_tended_before_the_tailnet(launch, records):
    run = launch(rounds=Rounds())
    run.rounds.next_end()  # round 1: both open
    started = []
    real = serving._start_serving

    async def recording(server):
        started.append(1)
        run.calls.append("start_serving")
        await real(server)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(serving, "_start_serving", recording)
        run.on_loop(lambda: run.loopback.server.close())  # the loopback listener is lost
        run.runner.gate = threading.Event()
        run.runner.entered.clear()
        mark = len(run.calls)
        run.rounds.go()
        assert run.runner.entered.wait(GUARD)
        assert run.calls[mark:] == ["bind:loop", "start_serving", "runner"]
        assert http_get(run.port) == 200  # the reopened loopback answers, the runner still blocked
        run.runner.gate.set()
        run.rounds.next_end()


def test_shutdown_during_a_check_does_not_wait_for_the_runner(launch, records):
    gate = threading.Event()
    run = launch(rounds=Rounds(), on_call=lambda runner: setattr(runner, "gate", gate))
    assert run.runner.entered.wait(GUARD)
    run.server.should_exit = True
    # `serve` returned without waiting for the runner (nor for the 30 s interval).
    assert run.done.wait(GUARD)
    assert "surveillance des écoutes annulée" in records.serving(level=logging.DEBUG)
    gate.set()
    run.thread.join(GUARD)
    assert not run.thread.is_alive()
    assert run.bind.tail_count == 0


def test_shutdown_right_after_a_check_never_binds(launch):
    def stop_then_confirm(runner):
        runner.run.server.should_exit = True

    run = launch(rounds=Rounds(), on_call=stop_then_confirm)
    assert run.done.wait(GUARD)
    assert run.bind.tail_count == 0
    assert len(run.server.servers) == 1
