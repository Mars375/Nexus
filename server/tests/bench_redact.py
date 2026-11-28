"""Manual bench of `nexus.secrets.redact` (spec §7.1, plan PR 2 §2): never run in CI.

Throughput depends on the machine; the CI guard is `test_conversations_redact_rate.py`.
Usage: uv run --directory server python tests/bench_redact.py [--mib 20] [--seed 204]
       [--hash-weight 5] [--worst]
"""

from __future__ import annotations

import argparse
import base64
import random
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import redact_corpus as corpus  # noqa: E402

from nexus.secrets import redact  # noqa: E402

MIB = 1 << 20


def measure(mib: float, seed: int, hash_weight: float) -> None:
    messages = corpus.build(int(mib * MIB), seed=seed, hash_weight=hash_weight)
    size = sum(len(text.encode("utf-8")) for _, text in messages)
    per_kind: Counter = Counter()
    masked: Counter = Counter()
    durations = []
    for kind, text in messages:
        start = time.perf_counter()
        out, _ = redact(text)
        durations.append(time.perf_counter() - start)
        per_kind[kind] += 1
        masked[kind] += out != text
    elapsed = sum(durations)
    print(f"corpus : {len(messages)} messages, {size / MIB:.1f} Mio, graine {seed}")
    print(f"débit : {size / 1e6 / elapsed:.2f} Mo/s ({elapsed:.2f} s), médiane "
          f"{statistics.median(durations) * 1e3:.2f} ms, max {max(durations) * 1e3:.1f} ms")
    total = sum(masked.values())
    print(f"sur-masquage, tout le corpus : {total}/{len(messages)} = "
          f"{total / len(messages):.2%}")
    plain = [k for k in per_kind if k not in corpus.HASH_KINDS]
    n, m = sum(per_kind[k] for k in plain), sum(masked[k] for k in plain)
    print(f"sur-masquage, hors condensats : {m}/{n} = {m / n:.2%}")
    for kind in sorted(per_kind):
        print(f"  {kind:9s} {masked[kind]:6d}/{per_kind[kind]:6d}")
    left = sum(corpus.visible(s, redact(t)[0]) for s, t in corpus.seeded(2000, seed=seed + 1))
    print(f"secrets semés : 2000, laissés visibles : {left}")


def _ticker(stop: threading.Event, worst: list[float]) -> None:
    last = time.perf_counter()
    while not stop.is_set():
        time.sleep(0.001)
        now = time.perf_counter()
        worst[0] = max(worst[0], now - last)
        last = now


def _fill(make) -> str:
    parts, size = [], 0
    while size < MIB:
        part = make()
        parts.append(part)
        size += len(part)
    return "\n\n".join(parts)[:MIB]


def worst_cases() -> None:
    """1 MiB bodies (the line cap, spec §6.2) and the longest gap of a 1 ms ticker (the GIL)."""
    rng = random.Random(11)
    cases = {
        "prose": _fill(lambda: corpus.paragraph(rng, corpus.FR)),
        "code": _fill(lambda: corpus.code_block(rng)),
        "chemins": _fill(lambda: corpus.message(rng, "paths")),
        "base64": base64.b64encode(rng.randbytes(MIB * 3 // 4)).decode()[:MIB],
        "json minifié": ",".join(
            f'"{corpus.ident(rng)}":{rng.randint(0, 10**9)}' for _ in range(60000))[:MIB],
        "barres obliques": "/".join(corpus.ident(rng) for _ in range(90000))[:MIB],
        "SHA en série": " ".join(corpus.full_sha(rng) for _ in range(26000))[:MIB],
    }
    for name, text in cases.items():
        stop, worst = threading.Event(), [0.0]
        thread = threading.Thread(target=_ticker, args=(stop, worst))
        thread.start()
        try:
            time.sleep(0.05)
            worst[0] = 0.0
            start = time.perf_counter()
            redact(text)
            took = time.perf_counter() - start
        finally:  # an interrupt must not leave the ticker thread running
            stop.set()
            thread.join()
        size = len(text.encode("utf-8"))
        print(f"{name:16s} {took:5.2f} s  {size / 1e6 / took:5.2f} Mo/s  "
              f"écart max du fil témoin {worst[0] * 1e3:5.1f} ms")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mib", type=float, default=20.0)
    parser.add_argument("--seed", type=int, default=204)
    parser.add_argument("--hash-weight", type=float, default=5.0)
    parser.add_argument("--worst", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    measure(args.mib, args.seed, args.hash_weight)
    if args.worst:
        worst_cases()
    return 0


if __name__ == "__main__":
    sys.exit(main())
