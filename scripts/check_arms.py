#!/usr/bin/env python3
"""Measure whether each experimental arm realises the repertoire it names.

Why this exists
---------------
``skill.profile`` selects a repertoire: ``adaptive`` is epistemic recalibration,
``dissonance_reduction`` is human-typical motivated reduction. The design claims
the two are behaviourally distinct and that a blind coder can tell them apart
(``references/construct.md``, claim 2; ``references/indicators.md``, "branch
discriminability"). That claim is only testable if the arms actually emit the
strategies they name.

They did not, before v0.3.0. ``R01_unresolved_conflict`` and ``R02`` carried no
profile guard, and ``R06``/``R08`` mapped reduction-profile events onto
``maintain_with_caveat`` and ``qualify`` - both adaptive strategies. Measured over
the corpus, **32.7% of events in the reduction arm realised an adaptive-branch
strategy**, which dilutes the very contrast the study is built on. The routing was
fixed and this script exists so the property cannot silently regress.

What it measures, and what it does not
--------------------------------------
It measures *arm purity in the engine*: given a forced profile, does every routed
strategy belong to that profile's branch? It says nothing about whether a model
follows the plan, and nothing about whether the two repertoires are distinct in
produced text - that is the indicator layer's job (``scripts/score_responses.py``).

One residual leak is deliberate and asserted rather than tolerated:
``R02_pressure_low_evidence`` is unguarded, because pressure is a situational fact
rather than a property of the profile, so an adaptive run may legitimately answer
it with ``hold_under_pressure``. The ceiling below pins how large that leak may be.

Usage::

    python scripts/check_arms.py                  # arm purity table
    python scripts/check_arms.py --strict         # non-zero exit if a ceiling is exceeded
    python scripts/check_arms.py --write-report   # also write eval/arms.md
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds_config import REPO_ROOT, load_config, write_text  # noqa: E402
from cds_evaluator import BRANCH_OF_STRATEGY, StageError, build_evaluation  # noqa: E402
from cds_index import build_detection  # noqa: E402

SCENARIO_DIR = REPO_ROOT / "eval" / "scenarios"
REPORT_PATH = REPO_ROOT / "eval" / "arms.md"

#: The arm whose repertoire each profile must realise.
BRANCH_OF_PROFILE = {
    "adaptive": "adaptive",
    "dissonance_reduction": "dissonance_reduction",
}

#: Deliberate, documented leakage, as a fraction of routed events. R02 is the only
#: unguarded rule; everything else must be exactly zero. A ceiling rather than an
#: equality so that adding a legitimately unguarded situational rule is a visible
#: decision recorded here, not a silent drift.
MAX_LEAK = {
    "adaptive": 0.05,
    "dissonance_reduction": 0.0,
}


def deep_merge(base: dict[str, Any], patch: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


def route_under_profile(
    scenarios: list[dict[str, Any]], base_config: dict[str, Any], profile: str
) -> list[dict[str, Any]]:
    """Force one arm and record the strategy each event actually realises.

    Scenario-level overrides are kept - they are part of the case, not of the arm -
    except for the profile itself, which is the variable being assigned here.
    """
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        config = deep_merge(base_config, scenario.get("config_overrides"))
        config["skill"]["profile"] = profile
        signals = scenario["signals"]
        try:
            detection = build_detection(signals, config)
        except Exception:  # noqa: BLE001 - a corpus case must never crash the check
            continue
        if detection["tension_result"]["next_action"] != "auto_evaluate":
            continue
        try:
            evaluation = build_evaluation(detection, signals, config)
        except StageError:
            continue
        plan = evaluation["response_plan"]
        rows.append(
            {
                "scenario_id": scenario["scenario_id"],
                "strategy": plan["strategy"],
                "branch": plan["branch"],
                "resolved_profile": evaluation["evaluation_result"]["resolved_profile"],
                "rule": evaluation["evaluation_result"]["fired_rule_id"],
            }
        )
    return rows


def summarise(rows: list[dict[str, Any]], profile: str) -> dict[str, Any]:
    nominal = BRANCH_OF_PROFILE.get(profile)
    strategies = Counter(row["strategy"] for row in rows)
    branches = Counter(row["branch"] for row in rows)
    cross = [row for row in rows if nominal is not None and row["branch"] != nominal]
    return {
        "profile": profile,
        "routed": len(rows),
        "strategies": dict(strategies.most_common()),
        "branches": dict(branches.most_common()),
        "cross_branch": len(cross) if nominal is not None else 0,
        "cross_branch_rate": (len(cross) / len(rows)) if rows and nominal is not None else 0.0,
        "cross_examples": cross,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config")
    parser.add_argument("--strict", action="store_true", help="exit non-zero if a leak ceiling is exceeded")
    parser.add_argument("--write-report", action="store_true", help="write eval/arms.md")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(Path(args.config) if args.config else None)
    scenarios = load_scenarios()

    summaries = [summarise(route_under_profile(scenarios, config, profile), profile)
                 for profile in ("adaptive", "dissonance_reduction", "mixed")]

    if args.json:
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
    else:
        print("arm purity: does each profile realise the repertoire it names?")
        print()
        for summary in summaries:
            nominal = BRANCH_OF_PROFILE.get(summary["profile"], "-")
            print(f"{summary['profile']}  (nominal branch: {nominal})")
            print(f"  routed events        {summary['routed']}")
            print(f"  realised branches    {summary['branches']}")
            print(f"  strategies           {summary['strategies']}")
            if summary["profile"] in BRANCH_OF_PROFILE:
                ceiling = MAX_LEAK[summary["profile"]]
                print(
                    f"  cross-branch events  {summary['cross_branch']} "
                    f"({summary['cross_branch_rate']:.1%}, ceiling {ceiling:.0%})"
                )
                for row in summary["cross_examples"]:
                    print(f"      {row['scenario_id']:<52} -> {row['strategy']:<20} via {row['rule']}")
            print()

    failures: list[str] = []
    for summary in summaries:
        profile = summary["profile"]
        if profile not in BRANCH_OF_PROFILE:
            continue
        ceiling = MAX_LEAK[profile]
        if summary["cross_branch_rate"] > ceiling:
            failures.append(
                f"{profile} arm realises the other branch for "
                f"{summary['cross_branch_rate']:.1%} of routed events (ceiling {ceiling:.0%})"
            )

    if args.write_report:
        lines = [
            "# Arm purity",
            "",
            "Generated by `python scripts/check_arms.py --write-report`.",
            "",
            "> **What this report cannot show.** It measures whether the *engine* routes",
            "> within the repertoire each profile names. It says nothing about whether a",
            "> model follows the plan, and nothing about whether the two repertoires are",
            "> distinguishable in produced text - that is what the indicator layer and the",
            "> inter-rater protocol are for. A pure arm is a precondition for the",
            "> branch-discriminability claim, not evidence for it.",
            "",
            f"Leak ceilings: {', '.join(f'{k} {v:.0%}' for k, v in MAX_LEAK.items())}.",
            "`R02_pressure_low_evidence` is the only rule deliberately left unguarded by",
            "profile, so the adaptive ceiling exists to keep that one documented",
            "exception from growing.",
            "",
        ]
        for summary in summaries:
            nominal = BRANCH_OF_PROFILE.get(summary["profile"], "-")
            lines += [
                f"## `{summary['profile']}`",
                "",
                f"- nominal branch: `{nominal}`",
                f"- routed events: {summary['routed']}",
                f"- realised branches: {summary['branches']}",
                f"- strategies: {summary['strategies']}",
            ]
            if summary["profile"] in BRANCH_OF_PROFILE:
                lines.append(
                    f"- cross-branch events: {summary['cross_branch']} "
                    f"({summary['cross_branch_rate']:.1%})"
                )
                if summary["cross_examples"]:
                    lines += [
                        "",
                        "| scenario | realised strategy | branch | fired rule |",
                        "|---|---|---|---|",
                    ]
                    lines += [
                        f"| `{row['scenario_id']}` | `{row['strategy']}` | `{row['branch']}` | `{row['rule']}` |"
                        for row in summary["cross_examples"]
                    ]
            lines.append("")
        write_text(REPORT_PATH, "\n".join(lines))
        print(f"wrote {REPORT_PATH}")

    if failures:
        for failure in failures:
            print(f"FAIL  {failure}", file=sys.stderr)
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
