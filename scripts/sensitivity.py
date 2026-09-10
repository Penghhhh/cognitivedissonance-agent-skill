#!/usr/bin/env python3
"""Sensitivity analysis over the index weights, thresholds and structural choices.

Why this exists
---------------
The v0.1 proposal asserted a weighted sum with hand-set weights (0.30 / 0.25 /
0.20 / 0.15 / 0.10) and hand-set thresholds (0.35 / 0.55 / 0.75), citing nothing.
A reviewer is entitled to ask whether any conclusion survives perturbing them. If
a reported effect turns on the third decimal of a weight nobody calibrated, the
result is a property of the constants rather than of the phenomenon, and the
honest thing is to say so before the reviewer does.

This script answers three questions:

1. **Weight sensitivity** - perturb each index weight and report how often the
   level or the strategy label changes across the evaluation corpus.
2. **Threshold sensitivity** - sweep the alert threshold and report the same.
3. **Structural sensitivity** - recompute with the two design choices this
   repository made against v0.1, to show what they actually bought:
   ``volition_self`` as product versus mean, and novelty versus v0.1's inverted
   ``repetition`` term.

Usage::

    python scripts/sensitivity.py
    python scripts/sensitivity.py --delta 0.05 --write-report
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any, Callable

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds_config import REPO_ROOT, ConfigError, check_semantics, load_config  # noqa: E402
from cds_evaluator import StageError, build_evaluation  # noqa: E402
from cds_index import build_detection  # noqa: E402
from run_scenarios import deep_merge, load_scenarios  # noqa: E402

REPORT_PATH = REPO_ROOT / "eval" / "sensitivity.md"


def _renormalise(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return {key: 0.0 for key in weights}
    return {key: value / total for key, value in weights.items()}


def evaluate_corpus(
    config: dict[str, Any],
    scenarios: list[dict[str, Any]],
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[list[str | None], list[str | None]]:
    """Return the (level, strategy) labels the corpus produces under one config.

    A packet transform lets structural alternatives be tested without touching the
    engine: rewriting the packet is the only honest way to ask what a different
    volition rule would have done, because the rule is fixed in the index version.
    """
    levels: list[str | None] = []
    strategies: list[str | None] = []
    for scenario in scenarios:
        merged = deep_merge(config, scenario.get("config_overrides") or {})
        try:
            check_semantics(merged)
        except ConfigError:
            levels.append(None)
            strategies.append(None)
            continue
        signals = copy.deepcopy(scenario["signals"])
        if transform is not None:
            signals = transform(signals)
        try:
            detection = build_detection(signals, merged)
        except Exception:  # noqa: BLE001
            levels.append(None)
            strategies.append(None)
            continue
        levels.append(detection["tension_result"]["level"])
        if detection["tension_result"]["next_action"] == "auto_evaluate":
            try:
                evaluation = build_evaluation(detection, signals, merged)
                strategies.append(evaluation["evaluation_result"]["recommended_strategy"])
            except StageError:
                strategies.append(None)
        else:
            strategies.append(None)
    return levels, strategies


def flip_rate(baseline: list[Any], variant: list[Any]) -> float:
    comparable = [(a, b) for a, b in zip(baseline, variant) if a is not None and b is not None]
    if not comparable:
        return float("nan")
    return sum(1 for a, b in comparable if a != b) / len(comparable)


def weight_sweep(config: dict[str, Any], scenarios: list[dict[str, Any]], delta: float) -> list[dict[str, Any]]:
    base_levels, base_strategies = evaluate_corpus(config, scenarios)
    results = []
    names = list(config["index"]["weights"])
    for name in names:
        for direction in (+1, -1):
            weights = dict(config["index"]["weights"])
            weights[name] = max(0.0, min(1.0, weights[name] + direction * delta))
            variant = copy.deepcopy(config)
            variant["index"]["weights"] = _renormalise(weights)
            levels, strategies = evaluate_corpus(variant, scenarios)
            results.append(
                {
                    "weight": name,
                    "direction": "+" if direction > 0 else "-",
                    "value": variant["index"]["weights"][name],
                    "level_flip_rate": flip_rate(base_levels, levels),
                    "strategy_flip_rate": flip_rate(base_strategies, strategies),
                }
            )
    return results


def threshold_sweep(config: dict[str, Any], scenarios: list[dict[str, Any]], steps: list[float]) -> list[dict[str, Any]]:
    base_levels, base_strategies = evaluate_corpus(config, scenarios)
    results = []
    for value in steps:
        variant = copy.deepcopy(config)
        variant["thresholds"]["alert"] = value
        # Keep the gate invariant: the cap must stay strictly below every alert.
        cap = min(value, variant["index"]["gates"]["non_dissonant_cap"])
        variant["index"]["gates"]["non_dissonant_cap"] = max(0.0, cap - 0.01)
        levels, strategies = evaluate_corpus(variant, scenarios)
        results.append(
            {
                "alert": value,
                "level_flip_rate": flip_rate(base_levels, levels),
                "strategy_flip_rate": flip_rate(base_strategies, strategies),
                "fired": sum(1 for level in levels if level not in (None, "silent")),
            }
        )
    return results


def volition_mean_transform(signals: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a packet so ``volition * self_relevance`` equals their mean.

    Setting ``self_relevance`` to 1 and ``volition`` to the mean makes the product
    collapse to the mean, which is exactly the alternative rule under test.
    """
    stance = signals.get("stance")
    if not stance:
        return signals
    volition = float(stance.get("volition", 0.0))
    self_relevance = float(stance.get("self_relevance", 0.0))
    stance["volition"] = (volition + self_relevance) / 2.0
    stance["self_relevance"] = 1.0
    return signals


def repetition_transform(signals: dict[str, Any]) -> dict[str, Any]:
    """Reinstate v0.1's inverted term: repetition raises attention instead of novelty.

    The v0.1 formula added 0.10 * repetition, so a user restating a known objection
    scored higher than one raising a new one. Under that rule a maximally repeated,
    minimally novel objection should be the strongest trigger, which is what this
    transform simulates.
    """
    for item in signals.get("evidence") or []:
        if "novelty" in item:
            item["novelty"] = 1.0 - float(item["novelty"])
    return signals


def evaluator_weight_sweep(config: dict[str, Any], scenarios: list[dict[str, Any]], delta: float) -> list[dict[str, Any]]:
    """Perturb the evidence weights, which is where strategy routing actually lives.

    Without this sweep the strategy flip rate is vacuous: index weights move the
    *level*, and the threshold sweep moves the *level*, but neither touches
    ``E_score``, so the strategy label could look perfectly robust while never
    having been perturbed at all.
    """
    base_levels, base_strategies = evaluate_corpus(config, scenarios)
    results = []
    for name in config["evaluator"]["evidence_weights"]:
        for direction in (+1, -1):
            weights = dict(config["evaluator"]["evidence_weights"])
            weights[name] = max(0.0, min(1.0, weights[name] + direction * delta))
            variant = copy.deepcopy(config)
            variant["evaluator"]["evidence_weights"] = _renormalise(weights)
            levels, strategies = evaluate_corpus(variant, scenarios)
            results.append(
                {
                    "weight": name,
                    "direction": "+" if direction > 0 else "-",
                    "value": variant["evaluator"]["evidence_weights"][name],
                    "level_flip_rate": flip_rate(base_levels, levels),
                    "strategy_flip_rate": flip_rate(base_strategies, strategies),
                }
            )
    return results


def boundary_proximity(config: dict[str, Any], scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    """How close do the routed cases sit to the decision boundaries?

    A strategy flip rate of zero has two very different explanations: the routing
    is robust, or the corpus was authored with cases comfortably inside their bands.
    Reporting the distance distribution separates them, and without it a zero flip
    rate would read as a stronger result than it is.
    """
    rules = config["evaluator"]["strategy_rules"]["rules"]
    boundaries: set[float] = set()
    for rule in rules:
        for key, value in rule["if"].items():
            # Only E_score edges decide the strategy label. Collecting every
            # numeric condition would sweep in user_pressure and unresolved
            # thresholds and report a distance to constants that never touch
            # routing.
            if key.startswith("e_score_") and isinstance(value, (int, float)):
                boundaries.add(float(value))
    ordered = sorted(boundaries)

    distances: list[float] = []
    for scenario in scenarios:
        merged = deep_merge(config, scenario.get("config_overrides") or {})
        signals = scenario["signals"]
        try:
            detection = build_detection(signals, merged)
            if detection["tension_result"]["next_action"] != "auto_evaluate":
                continue
            evaluation = build_evaluation(detection, signals, merged)
        except Exception:  # noqa: BLE001
            continue
        score = evaluation["evaluation_result"]["evidence_score"]
        distances.append(min(abs(score - edge) for edge in ordered))

    if not distances:
        return {"n": 0, "boundaries": ordered, "min": None, "median": None, "within_delta": 0}
    distances.sort()
    return {
        "n": len(distances),
        "boundaries": ordered,
        "min": distances[0],
        "median": distances[len(distances) // 2],
        "within_delta": sum(1 for value in distances if value <= 0.05),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config")
    parser.add_argument("--delta", type=float, default=0.05, help="weight perturbation size (default 0.05)")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    scenarios = load_scenarios()
    if not scenarios:
        print("no scenarios found; run the corpus generator first", file=sys.stderr)
        return 2

    base_levels, base_strategies = evaluate_corpus(config, scenarios)
    fired = sum(1 for level in base_levels if level not in (None, "silent"))

    print(f"corpus           {len(scenarios)} scenarios, {fired} fire at the baseline config")
    print(f"weight delta     ±{args.delta}")
    print()

    weights = weight_sweep(config, scenarios, args.delta)
    print("index weight perturbation (level flip / strategy flip)")
    print("weight           dir   value   level    strategy")
    print("---------------  ----  ------  -------  --------")
    for row in weights:
        print(
            f"{row['weight']:<15}  {row['direction']:<4}  {row['value']:.3f}  "
            f"{row['level_flip_rate']:.3f}    {row['strategy_flip_rate']:.3f}"
        )

    alert_flips = [row["level_flip_rate"] for row in weights]
    worst = max(alert_flips)
    print()
    print(f"worst weight perturbation moves {worst * 100:.1f}% of the corpus to a different level")

    evaluator_weights = evaluator_weight_sweep(config, scenarios, args.delta)
    print()
    print("evidence weight perturbation (where the strategy label is decided)")
    print("weight           dir   value   level    strategy")
    print("---------------  ----  ------  -------  --------")
    for row in evaluator_weights:
        print(
            f"{row['weight']:<15}  {row['direction']:<4}  {row['value']:.3f}  "
            f"{row['level_flip_rate']:.3f}    {row['strategy_flip_rate']:.3f}"
        )
    worst_strategy = max(row["strategy_flip_rate"] for row in evaluator_weights)
    print()
    print(f"worst evidence perturbation moves {worst_strategy * 100:.1f}% of routed cases to a different strategy")

    proximity = boundary_proximity(config, scenarios)
    print()
    if proximity["n"]:
        print("routing boundary proximity (explains a zero strategy flip rate)")
        print(f"  routed cases                          {proximity['n']}")
        print(f"  e_score boundaries in the rule list   {proximity['boundaries']}")
        print(f"  nearest boundary: min / median        {proximity['min']:.3f} / {proximity['median']:.3f}")
        print(f"  cases within 0.05 of a boundary       {proximity['within_delta']}")
        if proximity["median"] > 0.10:
            print("  -> the corpus sits comfortably inside its bands, so a zero flip")
            print("     rate reflects corpus design as much as routing robustness.")
    else:
        print("routing boundary proximity: no routed cases to measure")

    steps = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    print()
    print("alert threshold sweep")
    print("alert  level flip  strategy flip  scenarios firing")
    print("-----  ----------  -------------  ----------------")
    thresholds = threshold_sweep(config, scenarios, steps)
    for row in thresholds:
        print(
            f"{row['alert']:.2f}   {row['level_flip_rate']:.3f}       "
            f"{row['strategy_flip_rate']:.3f}          {row['fired']}"
        )
    firing_counts = [row["fired"] for row in thresholds]
    print()
    print(f"firing count ranges from {min(firing_counts)} to {max(firing_counts)} across the sweep")

    print()
    print("structural alternatives")
    variants = {
        "volition_self = mean(v, s)": volition_mean_transform,
        "novelty replaced by v0.1 repetition": repetition_transform,
    }
    structural_rows = []
    for label, transform in variants.items():
        levels, strategies = evaluate_corpus(config, scenarios, transform)
        row = {
            "variant": label,
            "level_flip_rate": flip_rate(base_levels, levels),
            "strategy_flip_rate": flip_rate(base_strategies, strategies),
            "fired": sum(1 for level in levels if level not in (None, "silent")),
        }
        structural_rows.append(row)
        print(
            f"{label:<38}  level flip {row['level_flip_rate']:.3f}  "
            f"strategy flip {row['strategy_flip_rate']:.3f}  fired {row['fired']}"
        )

    if args.write_report:
        lines = [
            "# Sensitivity analysis",
            "",
            "Generated by `python scripts/sensitivity.py --write-report`.",
            "See the module docstring for what each sweep means and why it is reported.",
            "",
            f"- corpus size: {len(scenarios)}",
            f"- firing at the baseline config: {fired}",
            f"- weight perturbation: ±{args.delta}",
            "",
            "## Index weight perturbation",
            "",
            "| weight | direction | value | level flip rate | strategy flip rate |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {row['weight']} | {row['direction']} | {row['value']:.3f} | "
            f"{row['level_flip_rate']:.3f} | {row['strategy_flip_rate']:.3f} |"
            for row in weights
        ]
        lines += [
            "",
            "## Evidence weight perturbation",
            "",
            "The strategy label is decided here, so this is the sweep that tests it.",
            "",
            "| weight | direction | value | level flip rate | strategy flip rate |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {row['weight']} | {row['direction']} | {row['value']:.3f} | "
            f"{row['level_flip_rate']:.3f} | {row['strategy_flip_rate']:.3f} |"
            for row in evaluator_weights
        ]
        lines += [
            "",
            "## Alert threshold sweep",
            "",
            "| alert | level flip rate | strategy flip rate | scenarios firing |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {row['alert']:.2f} | {row['level_flip_rate']:.3f} | {row['strategy_flip_rate']:.3f} | {row['fired']} |"
            for row in thresholds
        ]
        lines += [
            "",
            "## Structural alternatives",
            "",
            "| variant | level flip rate | strategy flip rate | scenarios firing |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {row['variant']} | {row['level_flip_rate']:.3f} | {row['strategy_flip_rate']:.3f} | {row['fired']} |"
            for row in structural_rows
        ]
        lines.append("")
        REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
        print()
        print(f"wrote {REPORT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
