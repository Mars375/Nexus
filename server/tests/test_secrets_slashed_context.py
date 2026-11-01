"""Issue #144: a key chopped by its own slashes, written between path words.

`s3://bucket/<key>/backups/production`, `cat /etc/tokens/<key>`,
`C:/Users/loic/<key>/AppData` and `api/v1/<key>/download` used to leave the key
in the clear: the path words made the whole candidate read as a path. Every key
below is assembled at runtime so gitleaks never sees a secret in the repository.
"""

import random
import time

import pytest

from nexus import secrets
from nexus.secrets import redact

CONTEXTS = {
    "s3": "s3://bucket/{}/backups/production",
    "cat": "cat /etc/tokens/{}",
    "windows": "C:/Users/loic/{}/AppData",
    "url": "api/v1/{}/download",
}

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _key_a() -> str:
    return "/".join(["F1qH6Yytw" + "Me4Lbyo", "Fz8+uZd" + "Zv8F", "KIBJl" + "5dz"])


def _key_b() -> str:
    return "/".join(["xJ8byUs17" + "mQNVb7DnqRJ", "IlatOVd" + "Vhdwas" + "WF", "JbUU" + "EY8"])


def _sample(seed: int, count: int) -> list[str]:
    """Keys of 40 characters drawn from the standard base64 alphabet."""
    rng = random.Random(seed)
    return ["".join(rng.choice(_ALPHABET) for _ in range(40)) for _ in range(count)]


def _fragments(key: str, size: int = 8) -> set[str]:
    return {key[i : i + size] for i in range(len(key) - size + 1)}


def _whole_leaks(key: str, out: str) -> bool:
    return key in out


def _fragment_leaks(key: str, out: str) -> bool:
    return any(fragment in out for fragment in _fragments(key))


def _masked(context: str, key: str) -> str:
    return redact(CONTEXTS[context].format(key))[0]


def _no_segment_left(key: str, out: str) -> bool:
    return not any(part in out for part in key.split("/"))


# (context, key, path words that must stay readable)
EXACT = [
    pytest.param("s3", _key_a, ("bucket", "backups", "production"), id="s3-a"),
    pytest.param("cat", _key_a, ("etc", "tokens"), id="cat-a"),
    pytest.param("windows", _key_a, ("Users", "loic", "AppData"), id="windows-a"),
    pytest.param("url", _key_a, ("api", "v1", "download"), id="url-a"),
    pytest.param("s3", _key_b, ("bucket", "backups", "production"), id="s3-b"),
    # Already masked before the fix by the tail rule (cat-b, windows-b): regression guards.
    pytest.param("cat", _key_b, ("etc", "tokens"), id="cat-b"),
    pytest.param("windows", _key_b, ("Users",), id="windows-b"),
    pytest.param("url", _key_b, ("api", "v1", "download"), id="url-b"),
]


@pytest.mark.parametrize(("context", "make_key", "words"), EXACT)
def test_key_between_path_words_is_masked_and_the_words_stay(context, make_key, words):
    key = make_key()
    out = _masked(context, key)

    assert _no_segment_left(key, out), out
    assert secrets.REDACTED in out
    for word in words:
        assert word in out, (word, out)


def test_sample_of_400_keys_leaks_no_more_than_a_bare_key_plus_a_margin():
    # A key written alone is the floor of the scanner (limit of issue #84, a few
    # percent stay in the clear); a path around it must not add more than a
    # margin of 5 whole keys and 10 keys with a fragment of 8 characters or more.
    keys = _sample(95, 400)
    alone_whole = sum(_whole_leaks(key, redact(key)[0]) for key in keys)
    alone_fragment = sum(_fragment_leaks(key, redact(key)[0]) for key in keys)
    for context in CONTEXTS:
        outputs = [(key, _masked(context, key)) for key in keys]
        whole = sum(_whole_leaks(key, out) for key, out in outputs)
        fragment = sum(_fragment_leaks(key, out) for key, out in outputs)
        assert whole <= alone_whole + 5, (context, whole, alone_whole)
        assert fragment <= alone_fragment + 10, (context, fragment, alone_fragment)


def test_the_new_rule_only_adds_masks(monkeypatch):
    # Monotonicity: a fragment of 8 characters hidden without the window rule
    # stays hidden with it. The rule is switched off by replacing its entry
    # point (raising=False: the name does not exist before the fix, and the
    # comparison is then trivially equal).
    keys = _sample(95, 400)
    with monkeypatch.context() as patch:
        patch.setattr(secrets, "_mask_opaque_windows", lambda parts: None, raising=False)
        before = {
            (context, key): _masked(context, key) for context in CONTEXTS for key in keys
        }
    for (context, key), old in before.items():
        new = _masked(context, key)
        visible_now = {fragment for fragment in _fragments(key) if fragment in new}
        visible_before = {fragment for fragment in _fragments(key) if fragment in old}
        assert visible_now <= visible_before, (context, key)


def _ordinary_paths() -> list[str]:
    rng = random.Random(144)
    hex24 = "".join(rng.choice("0123456789abcdef") for _ in range(24))
    return [
        "api/v1beta2/projects/list",
        "api/v1beta2/rc1/arm64/download",
        "releases/v1.2/linux/arm64/rc1/nexus",
        "registry/images/arm64/v8/layers",
        f"storage/objects/{hex24}/metadata",
        f"api/v1/orders/{hex24}/items/download",
        f"cat /var/lib/data/{hex24}/index/current",
        "C:/Users/loic/AppData/Local/Temp/build42/output",
        "s3://bucket/exports/2026/10/18/report/part-0001",
        "deployments/20261018/rollout/blue/green",
        "src/nexus/migrations/versions/0004_add_index",
    ]


@pytest.mark.parametrize("path", _ordinary_paths())
def test_ordinary_rest_paths_are_not_over_masked(path):
    assert redact(path)[0] == path


def test_masking_a_path_around_a_key_reaches_a_fixed_point():
    for context in CONTEXTS:
        for key in _sample(2026, 60):
            once = _masked(context, key)
            assert redact(once)[0] == once, (context, key)


def test_window_rule_cost_grows_linearly_with_the_segments():
    # Relative bound as in the #134 test: four times the segments must cost about
    # four times as long. Best of several runs, with the same generous absolute
    # ceiling for a loaded runner.
    def best_of(parts, runs=5):
        sample = "s3://bucket/" + "/".join(["8SKDsHj+ePj"] * parts) + "/backups/production"
        times = []
        for _ in range(runs):
            started = time.perf_counter()
            redact(sample)
            times.append(time.perf_counter() - started)
        return min(times)

    small, large = best_of(1000), best_of(4000)
    assert large < 9 * max(small, 0.002) or large < 0.5, (small, large)


def _cascade_text() -> str:
    # Reviewer finding on PR 146: pass 1 masks the 24-character segment through
    # the entropy pass and keeps `rkEj`; pass 2 then judges the whole candidate
    # opaque. Built from pieces so no secret-looking literal sits in the repository.
    return "/".join(
        ["bkU2zUZo" + "1KtKuwgK", "backups", "MRS", "rkEj", "RvAskhR0" + "m2SH6VmZ7CVzoijr"]
    )


@pytest.mark.xfail(strict=True, reason="cascade between passes, PR 146 review")
def test_the_window_rule_does_not_change_what_the_passes_of_master_mask():
    text = _cascade_text()
    assert redact(text)[0] == f"{secrets.REDACTED}/{secrets.REDACTED}"


_SEGMENT_SIZES = (3, 4, 5, 6, 8, 12, 16, 24, 28, 32)
_PATH_WORDS = ["backups", "MRS", "logs", "tokens", "api", "v1", "data", "releases", "12"]


def _random_runs(count: int, seed: int = 144) -> list[str]:
    """Slashed runs with 2 to 5 opaque segments mixed with path words."""
    rng = random.Random(seed)
    alphabet = _ALPHABET.replace("/", "")
    runs = []
    for _ in range(count):
        parts = [
            "".join(rng.choice(alphabet) for _ in range(rng.choice(_SEGMENT_SIZES)))
            for _ in range(rng.randint(2, 5))
        ]
        for _ in range(rng.randint(0, 4)):
            parts.insert(rng.randint(0, len(parts)), rng.choice(_PATH_WORDS))
        runs.append("/".join(parts))
    return runs


def _visible_fragments(source: str, out: str) -> set[str]:
    return {source[i : i + 8] for i in range(len(source) - 7) if source[i : i + 8] in out}


@pytest.mark.xfail(strict=True, reason="cascade between passes, PR 146 review")
def test_the_rule_never_makes_a_hidden_fragment_readable_again(monkeypatch):
    assert hasattr(secrets, "_mask_opaque_windows")
    runs = _random_runs(20_000)
    with monkeypatch.context() as patch:
        patch.setattr(secrets, "_mask_opaque_windows", lambda parts: None, raising=True)
        without = [redact(run)[0] for run in runs]
    for run, old in zip(runs, without, strict=True):
        new = redact(run)[0]
        assert _visible_fragments(run, new) <= _visible_fragments(run, old), (run, old, new)


def test_runs_reach_a_fixed_point_before_the_pass_bound(monkeypatch):
    calls = 0
    original = secrets._redact_once

    def spy(value, *args):
        nonlocal calls
        calls += 1
        return original(value, *args)

    runs = _random_runs(3_000, seed=7)
    for run in runs:
        once = redact(run)[0]
        monkeypatch.setattr(secrets, "_redact_once", spy)
        calls = 0
        again = redact(once)[0]
        monkeypatch.setattr(secrets, "_redact_once", original)
        assert again == once, run
        assert calls < secrets._MAX_PASSES, (run, calls)


def test_concurrent_calls_do_not_share_the_window_collector():
    import threading

    texts_a = _random_runs(300, seed=1)
    texts_b = _random_runs(300, seed=2)
    alone_a = [redact(text)[0] for text in texts_a]
    alone_b = [redact(text)[0] for text in texts_b]
    results: dict[str, list[str]] = {}
    barrier = threading.Barrier(2)

    def work(name: str, texts: list[str]) -> None:
        barrier.wait()
        results[name] = [redact(text)[0] for text in texts]

    threads = [
        threading.Thread(target=work, args=("a", texts_a)),
        threading.Thread(target=work, args=("b", texts_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results["a"] == alone_a
    assert results["b"] == alone_b
