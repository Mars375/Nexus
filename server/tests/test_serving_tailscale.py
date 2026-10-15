"""Contrôle de l'adresse du tailnet auprès de Tailscale (ADR-021 D9), runner toujours factice."""

import asyncio
import ipaddress
import subprocess
import threading

import pytest

from nexus import nodes, serving

ADDRESS = ipaddress.ip_address("100.101.102.103")
CONFIRMING = '{"BackendState": "Running", "TailscaleIPs": ["100.101.102.103"]}'


def check(runner, timeout=5.0):
    return asyncio.run(serving.check_tailnet(runner, ADDRESS, timeout))


def raising(exc):
    def runner():
        raise exc

    return runner


def test_a_confirming_runner_gives_no_reason():
    assert check(lambda: CONFIRMING) is None


@pytest.mark.parametrize("exc,reason", [
    (FileNotFoundError("tailscale 100.101.102.103"), nodes.NOT_FOUND),
    (PermissionError("denied"), nodes.NOT_FOUND),
    (subprocess.CalledProcessError(1, "tailscale"), nodes.UNREADABLE),
    (subprocess.TimeoutExpired("tailscale", 5), nodes.NO_ANSWER),
    (TimeoutError("late"), nodes.NO_ANSWER),
    (RuntimeError("100.101.102.103 secret"), f"{nodes.CHECK_FAILED} (RuntimeError)"),
])
def test_check_reasons_for_runner_failures(exc, reason):
    assert check(raising(exc)) == reason


def test_a_reading_failure_fails_closed():
    assert check(lambda: "not json") == nodes.UNEXPECTED


def test_a_slow_runner_times_out_without_blocking_the_loop():
    entered, release = threading.Event(), threading.Event()

    def runner():
        entered.set()
        release.wait(timeout=30)
        return CONFIRMING

    async def scenario():
        sibling = asyncio.Event()
        asyncio.get_running_loop().call_soon(sibling.set)

        async def watch():
            await sibling.wait()
            return "ran"

        task = asyncio.create_task(watch())
        try:
            reason = await serving.check_tailnet(runner, ADDRESS, 0.2)
            return reason, await task
        finally:
            # Released inside the loop: `asyncio.run` waits for the executor's threads.
            release.set()

    reason, sibling_result = asyncio.run(scenario())
    assert entered.is_set()
    assert reason == nodes.NO_ANSWER
    assert sibling_result == "ran"


def test_check_does_not_swallow_cancellation():
    entered, release = threading.Event(), threading.Event()

    def runner():
        entered.set()
        release.wait(timeout=30)
        return CONFIRMING

    async def scenario():
        task = asyncio.create_task(serving.check_tailnet(runner, ADDRESS, 30))
        try:
            await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            await task
        finally:
            release.set()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scenario())
