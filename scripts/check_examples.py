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

# (packet, decision, reason). Mirrors the screening table in examples/README.md.
#
# The second row is the one worth having. It is a *real* conflict - above the alert
# threshold, on the dissonance channel - that the guard nevertheless holds back,
# because the interruption bar sits higher than the recording bar. If the two bars
# ever collapse into one, that row fails and the skill has become a nagger.
GUARD_EXPECTED: list[tuple[str, str, str]] = [
    ("triage_sparse_conflict.json", "surface", "policy_ask_user"),
    ("triage_sparse_quiet.json", "silent", "below_surface_threshold"),
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


def observe_guard(packet: Path) -> tuple[str, str]:
    """Screen one sparse packet and read back the decision and its first reason.

    Run statelessly on purpose: with no ``--state`` there is no cooldown, no
    dismissal memory and no budget, so the documented outcome is a function of the
    packet and the config alone. A documented example that depended on session
    history could not be re-run by a reader.
    """
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "cds.py"), "guard",
         "--signals", str(packet), "--no-log", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{packet.name}: cds.py guard exited {completed.returncode}\n{completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    reasons = payload.get("reasons") or [""]
    return payload["decision"], reasons[0]


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


#: Every generated report must say what it cannot show. The figures in these files
#: are precise-looking and easy to lift out of context, so the caveat is part of the
#: artifact rather than a note in a document nobody opens.
REQUIRED_CAVEATS = {
    "eval/report.md": "does **not** measure",
    "eval/sensitivity.md": "What this report cannot show",
    "eval/arms.md": "What this report cannot show",
    "eval/perception.md": "cannot show",
}


def check_report_caveats() -> int:
    """Fail if a generated report lost its "what this cannot show" block.

    ``run_scenarios.py`` already prints its circularity warning into the top of the
    report it generates, which is the single most honest artifact in the repository.
    The same discipline is extended to the other three reports here, and enforced,
    because a caveat that only survives until the next regeneration is not a caveat.
    """
    failures = 0
    for relative, marker in sorted(REQUIRED_CAVEATS.items()):
        path = REPO_ROOT / relative
        if not path.exists():
            print(f"FAIL {relative}: missing (regenerate it)")
            failures += 1
            continue
        if marker not in path.read_text(encoding="utf-8"):
            print(f"FAIL {relative}: required caveat block is absent (looked for {marker!r}).")
            print("     A generated report without its caveat reads as a stronger claim")
            print("     than the method supports. Restore it before committing.")
            failures += 1
        else:
            print(f"ok   {relative}: caveat present")
    return 1 if failures else 0


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

    print()
    print(f"{len(EXPECTED)} examples match the documented table in examples/README.md")

    for name, want_decision, want_reason in GUARD_EXPECTED:
        packet = EXAMPLES / name
        if not packet.exists():
            print(f"FAIL {name}: file not found")
            failures += 1
            continue
        got_decision, got_reason = observe_guard(packet)
        rendered = f"{got_decision} / {got_reason}"
        if (got_decision, got_reason) != (want_decision, want_reason):
            print(f"FAIL {name}: expected {want_decision} / {want_reason}, got {rendered}")
            failures += 1
        else:
            print(f"ok   {name}: {rendered}")

    if failures:
        print()
        print(f"{failures} example(s) no longer match examples/README.md.")
        print("Either the config changed in a way you did not intend, or the")
        print("documented table needs updating. Decide which, then re-run.")
        return 1

    print(f"{len(GUARD_EXPECTED)} screening examples match the documented table")

    documented = check_documented_test_count()
    print()
    caveats = check_report_caveats()
    return 1 if (failures or documented or caveats) else 0


if __name__ == "__main__":
    raise SystemExit(main())
