#!/usr/bin/env python3
"""Run the evaluation corpus against the deterministic engine and report metrics.

What this harness can and cannot measure
----------------------------------------
It scores the **engine**: given a signal packet, does the index land on the gold
level, does the gate hold, does the router pick the gold strategy, does the right
rule fire? That is a pure function of the packet and the config, so the harness is
fully deterministic and can run in CI on every commit.

It does **not** score perception. Whether the host model produces the *right*
signal packet from a raw conversation is a separate measurement, and conflating
the two is how a system like this gets credit for arithmetic while its actual
errors live in the ratings. Perception quality is measured by
``scripts/score_signals.py`` against the same corpus, with packets produced by a
model rather than by the gold annotator.

Usage::

    python scripts/run_scenarios.py                 # summary table
    python scripts/run_scenarios.py --strict        # non-zero exit on any mismatch
    python scripts/run_scenarios.py --write-report  # also write eval/report.md and eval/results.csv
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds_config import (  # noqa: E402
    REPO_ROOT,
    ConfigError,
    check_semantics,
    config_hash,
    load_config,
    write_text,
)
from cds_evaluator import StageError, build_evaluation  # noqa: E402
from cds_index import build_detection  # noqa: E402

SCENARIO_DIR = REPO_ROOT / "eval" / "scenarios"
REPORT_PATH = REPO_ROOT / "eval" / "report.md"
RESULTS_PATH = REPO_ROOT / "eval" / "results.csv"


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively overlay ``patch`` onto a copy of ``base``."""
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    scenarios = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        data.setdefault("scenario_id", path.stem)
        scenarios.append(data)
    return scenarios


def run_scenario(scenario: dict[str, Any], base_config: dict[str, Any]) -> dict[str, Any]:
    """Execute one scenario and return a flat result row."""
    config = deep_merge(base_config, scenario.get("config_overrides") or {})
    expect = scenario.get("expect") or {}
    signals = scenario["signals"]

    row: dict[str, Any] = {
        "scenario_id": scenario["scenario_id"],
        "family": scenario.get("family", "unfiled"),
        "config_hash": config_hash(config)[:19],
        "error": "",
        "tension": None,
        "gate_applied": None,
        "level": None,
        "channel": None,
        "conflict_type": None,
        "next_action": None,
        "strategy": None,
        "fired_rule_id": None,
        "evidence_score": None,
        "adjustment_cost": None,
    }

    try:
        check_semantics(config)
    except ConfigError as exc:
        row["error"] = f"config_override_invalid: {exc}"
        return _score(row, expect)

    try:
        detection = build_detection(signals, config)
    except Exception as exc:  # noqa: BLE001 - a corpus case must never crash the run
        row["error"] = f"detect_failed: {type(exc).__name__}: {exc}"
        return _score(row, expect)

    tension = detection["tension_result"]
    row.update(
        {
            "tension": round(tension["tension"], 4),
            "gate_applied": detection["conflict_event"]["gate"]["applied"],
            "level": tension["level"],
            "channel": tension["channel"],
            "conflict_type": detection["conflict_event"]["conflict_type"],
            "next_action": tension["next_action"],
        }
    )

    if tension["next_action"] == "auto_evaluate":
        try:
            evaluation = build_evaluation(detection, signals, config)
        except StageError as exc:
            row["error"] = f"evaluate_failed: {exc}"
            return _score(row, expect)
        row.update(
            {
                "strategy": evaluation["evaluation_result"]["recommended_strategy"],
                "fired_rule_id": evaluation["evaluation_result"]["fired_rule_id"],
                "evidence_score": round(evaluation["evaluation_result"]["evidence_score"], 4),
                "adjustment_cost": round(evaluation["evaluation_result"]["adjustment_cost"], 4),
            }
        )

    return _score(row, expect)


def _score(row: dict[str, Any], expect: dict[str, Any]) -> dict[str, Any]:
    """Compare a result row against the gold expectations."""
    if row["error"]:
        row.update({"ok": False, "level_ok": False, "channel_ok": False, "type_ok": False,
                    "gate_ok": False, "strategy_ok": False, "rule_ok": False})
        return row

    def matches(gold_key: str, actual: Any) -> bool:
        gold = expect.get(gold_key)
        return gold is None or gold == actual

    strategy_set = expect.get("strategy_set")
    if strategy_set:
        strategy_ok = row["strategy"] in strategy_set
    else:
        strategy_ok = matches("strategy", row["strategy"])

    rule_prefix = expect.get("fired_rule_prefix")
    rule_ok = rule_prefix is None or (row["fired_rule_id"] or "").startswith(rule_prefix)

    checks = {
        "level_ok": matches("level", row["level"]),
        "channel_ok": matches("channel", row["channel"]),
        "type_ok": matches("conflict_type", row["conflict_type"]),
        "gate_ok": matches("gate_applied", row["gate_applied"]),
        "next_action_ok": matches("next_action", row["next_action"]),
        "strategy_ok": strategy_ok,
        "rule_ok": rule_ok,
    }
    row.update(checks)
    row["ok"] = all(checks.values())
    return row


def binary_detection_metrics(rows: list[dict[str, Any]], scenarios: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Precision/recall/F1 for 'did the engine report a conflict at all?'."""
    tp = fp = fn = tn = 0
    for row in rows:
        scenario = scenarios[row["scenario_id"]]
        gold_fired = (scenario.get("expect") or {}).get("level") not in (None, "silent")
        predicted_fired = row["level"] not in (None, "silent")
        if gold_fired and predicted_fired:
            tp += 1
        elif gold_fired and not predicted_fired:
            fn += 1
        elif not gold_fired and predicted_fired:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if precision and recall and precision + recall else float("nan")
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "false_positive_rate": fp / (fp + tn) if fp + tn else float("nan"),
        "false_negative_rate": fn / (fn + tp) if fn + tp else float("nan"),
    }


def summarise(rows: list[dict[str, Any]], scenarios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    families: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        families.setdefault(row["family"], []).append(row)

    def rate(subset: list[dict[str, Any]], key: str) -> float:
        graded = [row for row in subset if not row["error"] and row.get(key) is not None]
        if not graded:
            return float("nan")
        return sum(1 for row in graded if row[key]) / len(graded)

    return {
        "total": len(rows),
        "errors": sum(1 for row in rows if row["error"]),
        "exact_match_rate": rate(rows, "ok"),
        "binary": binary_detection_metrics(rows, scenarios),
        "per_check": {
            key: rate(rows, key)
            for key in ("level_ok", "channel_ok", "type_ok", "gate_ok", "next_action_ok", "strategy_ok", "rule_ok")
        },
        "per_family": {
            family: {
                "n": len(subset),
                "exact_match_rate": rate(subset, "ok"),
                "level_ok": rate(subset, "level_ok"),
                "strategy_ok": rate(subset, "strategy_ok"),
            }
            for family, subset in sorted(families.items())
        },
    }


def _format_rate(value: float) -> str:
    return "n/a" if value != value else f"{value:.3f}"  # NaN-safe


def print_summary(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    print(f"scenarios      {summary['total']}")
    if summary["errors"]:
        print(f"harness errors {summary['errors']}")
    print(f"exact match    {_format_rate(summary['exact_match_rate'])}")
    print()
    print("What this number is: verification that the engine computes what the")
    print("specification says. What it is NOT: evidence that the ratings, the")
    print("weights or the thresholds are correct. The expectations were derived")
    print("from the same formulas the engine implements, so a perfect score is")
    print("the expected outcome of a correct implementation, not a validation.")
    print("Perception quality needs a model and is measured separately.")
    print()
    print("check            pass rate")
    print("---------------  ---------")
    for key, value in summary["per_check"].items():
        print(f"{key:<15}  {_format_rate(value)}")
    print()
    binary = summary["binary"]
    print("binary conflict detection")
    print(f"  tp={binary['tp']} fp={binary['fp']} fn={binary['fn']} tn={binary['tn']}")
    print(
        f"  precision={_format_rate(binary['precision'])} recall={_format_rate(binary['recall'])} "
        f"f1={_format_rate(binary['f1'])}"
    )
    print()
    print("family                       n   exact   level  strategy")
    print("---------------------------  --  ------  ------  --------")
    for family, stats in summary["per_family"].items():
        print(
            f"{family:<27}  {stats['n']:>2}  {_format_rate(stats['exact_match_rate'])}  "
            f"{_format_rate(stats['level_ok'])}  {_format_rate(stats['strategy_ok'])}"
        )

    failures = [row for row in rows if not row["ok"]]
    if failures:
        print()
        print(f"mismatches ({len(failures)}):")
        for row in failures[:40]:
            detail = row["error"] or (
                f"level {row['level']} channel {row['channel']} type {row['conflict_type']} "
                f"gate {row['gate_applied']} strategy {row['strategy']} rule {row['fired_rule_id']}"
            )
            print(f"  - {row['scenario_id']}: {detail}")
        if len(failures) > 40:
            print(f"  ... and {len(failures) - 40} more (see eval/results.csv)")


def write_report(rows: list[dict[str, Any]], summary: dict[str, Any], base_config: dict[str, Any]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scenario_id", "family", "error", "tension", "gate_applied", "level", "channel",
        "conflict_type", "next_action", "strategy", "fired_rule_id", "evidence_score",
        "adjustment_cost", "ok", "level_ok", "channel_ok", "type_ok", "gate_ok",
        "next_action_ok", "strategy_ok", "rule_ok", "config_hash",
    ]
    with RESULTS_PATH.open("w", encoding="utf-8", newline="") as handle:
        # lineterminator="\n" overrides the csv module's RFC-4180 default of CRLF.
        # Left at the default, results.csv would carry CRLF on every platform while
        # the rest of the repository is LF, and .gitattributes normalises it away on
        # commit — so the working tree and the index would disagree forever.
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})

    lines = [
        "# Evaluation corpus report",
        "",
        "Generated by `python scripts/run_scenarios.py --write-report`.",
        "",
        "> **Read this before citing the numbers below.** This harness verifies that",
        "> the engine computes what the specification says. It does **not** measure",
        "> whether the ratings, weights or thresholds are correct. The expectations",
        "> were derived from the same formulas the engine implements, so a perfect",
        "> exact-match rate is the expected outcome of a correct implementation",
        "> rather than evidence of construct validity. Perception quality requires a",
        "> model in the loop and is measured separately. See",
        "> [`../references/construct.md`](../references/construct.md) for what this",
        "> artifact does and does not claim to measure.",
        "",
        f"- base config hash: `{config_hash(base_config)}`",
        f"- scenarios: {summary['total']}",
        f"- exact match rate: {_format_rate(summary['exact_match_rate'])}",
        "",
        "## Per-check pass rates",
        "",
        "| check | pass rate |",
        "|---|---|",
    ]
    for key, value in summary["per_check"].items():
        lines.append(f"| {key} | {_format_rate(value)} |")

    binary = summary["binary"]
    lines += [
        "",
        "## Binary conflict detection",
        "",
        "| tp | fp | fn | tn | precision | recall | f1 |",
        "|---|---|---|---|---|---|---|",
        f"| {binary['tp']} | {binary['fp']} | {binary['fn']} | {binary['tn']} | "
        f"{_format_rate(binary['precision'])} | {_format_rate(binary['recall'])} | {_format_rate(binary['f1'])} |",
        "",
        "## Per family",
        "",
        "| family | n | exact | level | strategy |",
        "|---|---|---|---|---|",
    ]
    for family, stats in summary["per_family"].items():
        lines.append(
            f"| {family} | {stats['n']} | {_format_rate(stats['exact_match_rate'])} | "
            f"{_format_rate(stats['level_ok'])} | {_format_rate(stats['strategy_ok'])} |"
        )

    failures = [row for row in rows if not row["ok"]]
    lines += ["", f"## Mismatches ({len(failures)})", ""]
    if failures:
        lines += ["| scenario | detail |", "|---|---|"]
        for row in failures:
            detail = row["error"] or (
                f"level={row['level']} channel={row['channel']} type={row['conflict_type']} "
                f"gate={row['gate_applied']} strategy={row['strategy']} rule={row['fired_rule_id']}"
            )
            lines.append(f"| `{row['scenario_id']}` | {detail} |")
    else:
        lines.append("None.")
    lines.append("")

    write_text(REPORT_PATH, "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="base config to merge scenario overrides onto")
    parser.add_argument("--strict", action="store_true", help="exit non-zero if any scenario mismatches")
    parser.add_argument("--write-report", action="store_true", help="write eval/report.md and eval/results.csv")
    parser.add_argument("--family", help="run only one family")
    args = parser.parse_args(argv)

    base_config = load_config(args.config)
    scenarios = load_scenarios()
    if args.family:
        scenarios = [s for s in scenarios if s.get("family") == args.family]

    if not scenarios:
        print(f"no scenarios found under {SCENARIO_DIR}", file=sys.stderr)
        return 2

    by_id = {scenario["scenario_id"]: scenario for scenario in scenarios}
    rows = [run_scenario(scenario, base_config) for scenario in scenarios]
    summary = summarise(rows, by_id)
    print_summary(rows, summary)

    if args.write_report:
        write_report(rows, summary, base_config)
        print()
        print(f"wrote {REPORT_PATH}")
        print(f"wrote {RESULTS_PATH}")

    if args.strict and (summary["errors"] or summary["exact_match_rate"] < 1.0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
