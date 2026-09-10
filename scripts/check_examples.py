#!/usr/bin/env python3
"""Verify that the shipped example packets produce the behaviour the docs claim.

``examples/README.md`` publishes a table of expected outcomes. A table in
documentation and a check in CI are usually two different things that drift apart;
this script makes the documented table executable, so a config change that moves an
example's label fails the build instead of silently falsifying the README.

It exists as a Python script rather than a shell block so that it runs identically
on Linux and Windows CI runners and can be exercised by the test suite locally.

Usage::

    python scripts/check_examples.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

# (packet, level, channel, strategy). `None` strategy means "routing does not run".
# This mirrors the table at the top of examples/README.md.
EXPECTED: list[tuple[str, str, str, str | None]] = [
    ("packet_evidence_vs_stance.json", "alert", "dissonance", "qualify"),
    ("packet_indeterminacy.json", "high", "indeterminacy", "suspend_and_verify"),
    ("packet_assigned_stance.json", "silent", "none", None),
    ("packet_pressure.json", "alert", "dissonance", "hold_under_pressure"),
    ("packet_no_conflict.json", "silent", "none", None),
]


def observe(packet: Path) -> tuple[str, str, str | None]:
    """Run one packet through the engine and read back the three labels.

    ``encoding`` is pinned to UTF-8 rather than left to the locale. ``cds.py``
    reconfigures its streams to UTF-8 and emits non-ASCII card text, so on a
    Chinese or Japanese Windows runner the default (GBK/cp932) codec raises
    ``UnicodeDecodeError`` before any assertion runs. Letting the parent and child
    disagree about encoding is a portability defect, not a test failure.
    """
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "cds.py"), "run",
         "--signals", str(packet), "--no-log", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{packet.name}: cds.py exited {completed.returncode}\n{completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    tension = payload["detection"]["tension_result"]
    evaluation = payload["evaluation"]
    strategy = evaluation["evaluation_result"]["recommended_strategy"] if evaluation else None
    return tension["level"], tension["channel"], strategy


def main() -> int:
    failures = 0
    for name, want_level, want_channel, want_strategy in EXPECTED:
        packet = EXAMPLES / name
        if not packet.exists():
            print(f"FAIL {name}: file not found")
            failures += 1
            continue
        got_level, got_channel, got_strategy = observe(packet)
        want = (want_level, want_channel, want_strategy)
        got = (got_level, got_channel, got_strategy)
        rendered = f"{got_level} / {got_channel} / {got_strategy or '-'}"
        if got != want:
            expected_text = f"{want_level} / {want_channel} / {want_strategy or '-'}"
            print(f"FAIL {name}: expected {expected_text}, got {rendered}")
            failures += 1
        else:
            print(f"ok   {name}: {rendered}")

    if failures:
        print()
        print(f"{failures} example(s) no longer match examples/README.md.")
        print("Either the config changed in a way you did not intend, or the")
        print("documented table needs updating. Decide which, then re-run.")
        return 1

    print()
    print(f"{len(EXPECTED)} examples match the documented table in examples/README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
