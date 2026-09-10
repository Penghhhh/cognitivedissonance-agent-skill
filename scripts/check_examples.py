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
import re
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
TESTS = REPO_ROOT / "tests"
README = REPO_ROOT / "README.md"

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


def test_count():
    """Number of test methods in ``tests/``, counted the way the README states it.

    Skip ``.scratch`` and ``__pycache__``. ``context.scratch_dir`` writes
    disposable copies into ``tests/.scratch/``, and a test that shells out to this
    script makes ``tests/__pycache__`` a package directory; counting either would
    make the figure depend on leftover artefacts rather than on the suite.
    """
    total = 0
    for path in sorted(TESTS.glob("test_*.py")):
        if any(part in {".scratch", "__pycache__"} for part in path.parts):
            continue
        total += len(re.findall(r"^\s+def test_", path.read_text(encoding="utf-8"), re.MULTILINE))
    return total


def check_documented_test_count() -> int:
    """The README publishes a test count. It has drifted before; hold it to the code.

    A number in prose is the easiest kind of claim to leave behind, and this
    repository asks reviewers to reproduce its figures. Counting the tests here
    makes the claim executable instead of aspirational.
    """
    text = README.read_text(encoding="utf-8")
    actual = test_count()
    if not re.search(rf"\b{actual}\b\s+stdlib\s+`?unittest`?\s+tests?", text):
        print(f"FAIL README.md does not state the actual test count ({actual}).")
        print("     Update the count in README.md, or add the missing tests.")
        return 1
    print(f"     README states the actual test count ({actual})")
    return 0


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
    documented = check_documented_test_count()
    return 1 if (failures or documented) else 0


if __name__ == "__main__":
    raise SystemExit(main())
