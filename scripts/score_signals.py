#!/usr/bin/env python3
"""Score model-produced signal packets against the gold annotations.

What this measures
------------------
``scripts/run_scenarios.py`` scores the **engine**: given a packet, does the index
land on the gold level, does the gate hold, does the router pick the gold strategy?
That is a pure function of ``(signals, config)`` and it is verified on every commit.

This harness scores **perception**: given a packet a *model* produced from the raw
conversation, how far is it from the packet a *human* annotator wrote for the same
conversation, and what did that difference cost at the decision level? It reports:

1. **Rating agreement per dimension** — MAE, RMSE, bias (the mean signed error,
   model minus gold, so a positive value means the model rates the field higher
   than the annotator did) and the rate of ratings inside ``--tolerance``
   (default 0.05), for every 0-1 field the codebook anchors:
   ``relation.opposition``, ``relation.specificity``, ``stance.confidence``,
   ``stance.commitment``, ``stance.public_commitment``, ``stance.volition``,
   ``stance.self_relevance``, each evidence item's ``novelty`` and five evaluator
   dimensions, ``user_pressure``, ``evidence_conflict_unresolved``,
   ``consistency_gate.internal_contradiction`` and ``perception.confidence``.
2. **Categorical agreement** on ``relation.type``, with the confusion pairs. "The
   model called it indeterminacy where the annotator called it dissonance" is a
   qualitative failure that no MAE can surface.
3. **Downstream decision agreement** — level, channel, conflict_type, gate,
   ``next_action`` and strategy. Every packet, produced or gold, is run through
   :func:`run_scenarios.run_scenario`, i.e. the *same* code path the engine harness
   uses, with the scenario's ``config_overrides`` applied. Because both sides go
   through one engine, a decision mismatch is attributable to the packet and not to
   the arithmetic.
4. **Attribution.** Every mismatched decision carries the dimension(s) on which the
   produced packet deviated most from gold, so the error is traceable to a rating
   rather than to a bare label.

What this cannot show
---------------------
It measures agreement with gold annotations; it does **not** establish that the
gold annotations are correct. A model that reproduces a mis-annotated gold packet
scores perfectly, and a model that is right where the annotator was wrong is
penalised. It also does not measure reply quality: a packet can match gold exactly
and the reply built from it can still be unhelpful, sycophantic or wrong, because
reply quality is a separate measurement over the response stage. And it cannot
separate "the model rates differently" from "the codebook is ambiguous" — a
dimension with poor agreement is a finding about the construct as much as about the
model, which is why agreement is reported per dimension rather than pooled.

Finally, the decision-level numbers are reported *relative to the gold packet run
through the same engine*, not against the corpus ``expect`` block. That isolates
packet error from engine error; ``scripts/run_scenarios.py --strict`` is what pins
the engine to ``expect``.

Degrading without packets
-------------------------
CI runs on a repository that has no model packets, so a missing ``--packets``
directory is not an error: the harness reports that there is nothing to score and
exits 0. ``--strict`` then also exits 0, because there is no decision to disagree
with.

Usage::

    python scripts/score_signals.py --packets eval/model_packets
    python scripts/score_signals.py --packets eval/model_packets --json
    python scripts/score_signals.py --packets eval/model_packets --strict
    python scripts/score_signals.py --write-report          # nothing to score yet

Packet collection protocol (what the owner must produce)
-------------------------------------------------------
For each scenario in ``eval/scenarios/``, put the raw conversation in front of the
host model with ``references/prompts/detect.md`` and the codebook, and save the
returned packet as ``<packets_dir>/<scenario_id>.json`` — one file per scenario,
``<scenario_id>`` being the scenario's file stem (the ``scenario_id`` field and an
``eval_<scenario_id>`` ``run_id`` are accepted as fallbacks — a ``scenario_id`` key is
stripped before schema validation, because the signals schema does not allow it and a
collection convenience must not invalidate a packet). Set
``annotator`` to the model id so a report can name what produced the packets. Do
not let the model see the gold packet or the ``expect`` block. Run
``python scripts/score_signals.py --packets <packets_dir> --write-report`` and cite
``eval/perception.md``. ``eval/model_packets/`` is the conventional location: the
report records the directory as given, so a repo-relative path keeps the generated
file identical on Windows and Linux.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds_config import REPO_ROOT, config_hash, load_config, load_schema, write_text  # noqa: E402
from jsonschema_lite import validate  # noqa: E402
from run_scenarios import load_scenarios, run_scenario  # noqa: E402

SCENARIO_DIR = REPO_ROOT / "eval" / "scenarios"
REPORT_PATH = REPO_ROOT / "eval" / "perception.md"
DEFAULT_TOLERANCE = 0.05

# Continuous (0-1) fields, as dotted paths into a packet. The list is the codebook's
# rated surface: anything here has anchors in references/codebook.md, and anything
# not here is either derived by the engine (volition_self, tension) or free text.
SCALAR_PATHS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("relation.opposition", ("relation", "opposition")),
    ("relation.specificity", ("relation", "specificity")),
    ("stance.confidence", ("stance", "confidence")),
    ("stance.commitment", ("stance", "commitment")),
    ("stance.public_commitment", ("stance", "public_commitment")),
    ("stance.volition", ("stance", "volition")),
    ("stance.self_relevance", ("stance", "self_relevance")),
    ("user_pressure", ("user_pressure",)),
    ("evidence_conflict_unresolved", ("evidence_conflict_unresolved",)),
    ("consistency_gate.internal_contradiction", ("consistency_gate", "internal_contradiction")),
    ("perception.confidence", ("perception", "confidence")),
)

# Rated per evidence item. Reported as ``evidence.<dimension>``, pooled over items
# that were paired between the gold packet and the produced packet.
EVIDENCE_RATED: tuple[str, ...] = ("novelty", "relevance", "credibility", "recency", "independence", "consistency")

SCALAR_DIMENSIONS: tuple[str, ...] = tuple(name for name, _ in SCALAR_PATHS)
EVIDENCE_DIMENSIONS: tuple[str, ...] = tuple(f"evidence.{name}" for name in EVIDENCE_RATED)
ALL_DIMENSIONS: tuple[str, ...] = SCALAR_DIMENSIONS + EVIDENCE_DIMENSIONS

# One-line restatement of the anchor scales, so a reader of the report can tell what
# "right" meant without opening the codebook. Each is the 0.00 anchor versus the 1.00
# anchor; the intermediate anchors live in references/codebook.md.
DIMENSION_ANCHORS: dict[str, str] = {
    "relation.opposition": "0.00 different subject (both can be true) - 1.00 logically incompatible, same object and conditions",
    "relation.specificity": "0.00 vague unease - 1.00 quantity, source, date or method named and the exact claim it contradicts",
    "stance.confidence": "the agent's stated certainty; the codebook keeps it separate from commitment, so the two may differ",
    "stance.commitment": "0.00 a passing suggestion - 1.00 a premise of the agent's current plan",
    "stance.public_commitment": "0.00 never stated to this user - 1.00 asserted repeatedly and the user has acted on it",
    "stance.volition": "0.00 assigned by the system prompt or relayed from a tool - 1.00 generated by the agent with visible latitude",
    "stance.self_relevance": "0.00 a quoted fact with no agent contribution - 1.00 the agent's own judgement",
    "user_pressure": "0.00 no position expressed by the user - 1.00 an ultimatum; routes strategies, never enters the index",
    "evidence_conflict_unresolved": "0.00 the items agree - 1.00 directly contradictory findings of comparable quality; at/above the alert it fires indeterminacy",
    "consistency_gate.internal_contradiction": "0.00 internally coherent - 1.00 the same quantity asserted with different values",
    "perception.confidence": "the annotator's confidence in its own packet; logged, never used in the arithmetic",
    "evidence.novelty": "0.00 already stated in the session - 1.00 new information that changes what can be concluded",
    "evidence.relevance": "0.00 different question - 1.00 bears directly on exactly the claim the stance makes",
    "evidence.credibility": "0.00 anonymous assertion - 1.00 verifiable primary evidence with a stated method; not agreement",
    "evidence.recency": "0.00 superseded - 1.00 published after the stance was formed and describing the present",
    "evidence.independence": "0.00 the same source restated - 1.00 independent data, method and interest",
    "evidence.consistency": "0.00 flatly contradicts the other items - 1.00 corroborates them",
}

# The signals schema sets ``additionalProperties: false``, so a packet that carries a
# ``scenario_id`` — the documented collection convenience — is not a valid SignalPacket.
# Rather than reject the whole packet over a collection key, the key is stripped before
# validation and counted, so the report can say how many packets carried one.
COLLECTION_KEYS: tuple[str, ...] = ("scenario_id",)

# The decision surface. These are the fields a reviewer reads off a card; agreement on
# them is the number that says whether a rating error mattered.
DECISION_FIELDS: tuple[str, ...] = (
    "level",
    "channel",
    "conflict_type",
    "gate_applied",
    "next_action",
    "strategy",
)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _dig(node: Any, path: tuple[str, ...]) -> Any:
    """Follow a dotted path, returning ``None`` when any step is absent."""
    current = node
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _number(value: Any) -> float | None:
    """A rating, or ``None`` for anything that is not a number (``bool`` excluded)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fmt(value: Any, digits: int = 3) -> str:
    """NaN-safe, None-safe formatting, matching the other harnesses' reports."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_signed(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _round(value: float | None, digits: int = 6) -> float | None:
    """Round for the emitted JSON so a report does not carry float noise."""
    return None if value is None else round(value, digits)


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #


def error_metrics(pairs: list[tuple[float, float]], tolerance: float = DEFAULT_TOLERANCE) -> dict[str, Any]:
    """MAE, RMSE, bias and tolerance agreement over ``(gold, produced)`` pairs.

    ``bias`` is the mean signed error ``produced - gold``: positive means the model
    rates systematically higher than the annotator. A large bias with a small MAE is
    a calibration finding, not noise, which is why the two are reported side by side
    rather than pooled into one "accuracy".
    """
    if not pairs:
        return {
            "n": 0,
            "mae": None,
            "rmse": None,
            "bias": None,
            "exact_agreement": None,
            "within_tolerance": 0,
            "max_abs_error": None,
        }
    errors = [produced - gold for gold, produced in pairs]
    n = len(errors)
    within = sum(1 for error in errors if abs(error) <= tolerance)
    return {
        "n": n,
        "mae": _round(sum(abs(error) for error in errors) / n),
        "rmse": _round(math.sqrt(sum(error * error for error in errors) / n)),
        "bias": _round(sum(errors) / n),
        "exact_agreement": _round(within / n),
        "within_tolerance": within,
        "max_abs_error": _round(max(abs(error) for error in errors)),
    }


def categorical_agreement(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    """Agreement rate and the confusion pairs for a categorical field."""
    if not pairs:
        return {"n": 0, "agreement": None, "confusions": []}
    confusions: dict[tuple[Any, Any], int] = {}
    for gold, produced in pairs:
        if gold != produced:
            confusions[(gold, produced)] = confusions.get((gold, produced), 0) + 1
    agree = sum(1 for gold, produced in pairs if gold == produced)
    ordered = sorted(confusions.items(), key=lambda item: (-item[1], str(item[0][0]), str(item[0][1])))
    return {
        "n": len(pairs),
        "agreement": _round(agree / len(pairs)),
        "confusions": [
            {"gold": gold, "produced": produced, "count": count} for (gold, produced), count in ordered
        ],
    }


def compare_decisions(reference: dict[str, Any], produced: dict[str, Any]) -> dict[str, bool]:
    """Per-field equality of two engine rows, plus an ``all`` roll-up.

    An engine failure on either side is never agreement, whatever the fields happen
    to hold: a packet that the engine rejects has no decision to compare, and
    counting the resulting ``None``s as a match would reward a packet for being
    unreadable.
    """
    failed = bool(reference.get("error")) or bool(produced.get("error"))
    checks = {
        field: (not failed and reference.get(field) == produced.get(field))
        for field in DECISION_FIELDS
    }
    checks["all"] = all(checks[field] for field in DECISION_FIELDS)
    return checks


# --------------------------------------------------------------------------- #
# evidence alignment
# --------------------------------------------------------------------------- #


def pair_evidence(gold_items: list[dict[str, Any]], produced_items: list[dict[str, Any]]) -> tuple[list[tuple[dict, dict]], dict[str, int]]:
    """Align evidence items by id, then positionally for whatever is left.

    A model reading the raw conversation cannot know the annotator's evidence ids, so
    an id-only match would report zero coverage on exactly the packets this harness
    exists to score. Ids are tried first because an id match is a real claim about
    which item is which; the remaining items are then paired in order, and the mode
    counts are reported so a reader can see how much of the agreement rests on the
    weaker positional alignment.
    """
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    used = [False] * len(produced_items)
    by_id: dict[Any, int] = {}
    for index, item in enumerate(produced_items):
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id not in by_id:
            by_id[item_id] = index

    leftover_gold: list[dict[str, Any]] = []
    id_pairs = 0
    for gold_item in gold_items:
        gold_id = gold_item.get("id")
        index = by_id.get(gold_id) if isinstance(gold_id, str) else None
        if index is not None and not used[index]:
            used[index] = True
            id_pairs += 1
            pairs.append((gold_item, produced_items[index]))
        else:
            leftover_gold.append(gold_item)

    leftover_produced = [item for index, item in enumerate(produced_items) if not used[index]]
    position_pairs = min(len(leftover_gold), len(leftover_produced))
    for offset in range(position_pairs):
        pairs.append((leftover_gold[offset], leftover_produced[offset]))

    coverage = {
        "gold_items": len(gold_items),
        "produced_items": len(produced_items),
        "paired": len(pairs),
        "paired_by_id": id_pairs,
        "paired_by_position": position_pairs,
        "gold_unpaired": len(leftover_gold) - position_pairs,
        "produced_unpaired": len(leftover_produced) - position_pairs,
    }
    return pairs, coverage


# --------------------------------------------------------------------------- #
# per-scenario scoring
# --------------------------------------------------------------------------- #


def _empty_accumulator() -> dict[str, dict[str, Any]]:
    return {
        name: {"pairs": [], "produced_unrated": 0, "gold_unrated": 0}
        for name in ALL_DIMENSIONS
    }


def _record(entry: dict[str, Any], gold_value: float | None, produced_value: float | None) -> None:
    if gold_value is None and produced_value is None:
        return
    if gold_value is None:
        entry["gold_unrated"] += 1
        return
    if produced_value is None:
        entry["produced_unrated"] += 1
        return
    entry["pairs"].append((gold_value, produced_value))


def merge_accumulators(target: dict[str, dict[str, Any]], source: dict[str, dict[str, Any]]) -> None:
    """Fold one scenario's pairs into the corpus-wide accumulator."""
    for name, entry in source.items():
        target[name]["pairs"].extend(entry["pairs"])
        target[name]["produced_unrated"] += entry["produced_unrated"]
        target[name]["gold_unrated"] += entry["gold_unrated"]


def collect_pairs(
    gold_signals: dict[str, Any],
    produced_signals: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Collect comparable ``(gold, produced)`` ratings from one packet pair."""
    accumulator = _empty_accumulator()

    for name, path in SCALAR_PATHS:
        _record(accumulator[name], _number(_dig(gold_signals, path)), _number(_dig(produced_signals, path)))

    pairs, coverage = pair_evidence(
        [item for item in (gold_signals.get("evidence") or []) if isinstance(item, dict)],
        [item for item in (produced_signals.get("evidence") or []) if isinstance(item, dict)],
    )
    for gold_item, produced_item in pairs:
        for dimension in EVIDENCE_RATED:
            _record(
                accumulator[f"evidence.{dimension}"],
                _number(gold_item.get(dimension)),
                _number(produced_item.get(dimension)),
            )

    return accumulator, coverage


def attributions(
    gold_signals: dict[str, Any],
    produced_signals: dict[str, Any],
    tolerance: float = DEFAULT_TOLERANCE,
    limit: int = 3,
) -> list[str]:
    """The dimensions a produced packet deviated on most, largest deviation first.

    This is what turns a decision mismatch from a label into an explanation: the
    reader can see that the router disagreed because ``stance.commitment`` was rated
    0.70 by the annotator and 0.40 by the model, rather than being told only that the
    strategy differs. A ``relation.type`` disagreement is reported first because it is
    categorical and no deviation magnitude describes it.
    """
    notes: list[str] = []

    gold_type = _dig(gold_signals, ("relation", "type"))
    produced_type = _dig(produced_signals, ("relation", "type"))
    if gold_type != produced_type:
        notes.append(f"relation.type {gold_type} -> {produced_type}")

    deviations: list[tuple[float, str, str]] = []
    unrated: list[str] = []

    for name, path in SCALAR_PATHS:
        gold_value = _number(_dig(gold_signals, path))
        produced_value = _number(_dig(produced_signals, path))
        if gold_value is None:
            continue
        if produced_value is None:
            unrated.append(f"{name} (unrated by the model)")
            continue
        deviations.append(
            (abs(produced_value - gold_value), name, f"{name} {gold_value:.2f} -> {produced_value:.2f}")
        )

    pairs, _ = pair_evidence(
        [item for item in (gold_signals.get("evidence") or []) if isinstance(item, dict)],
        [item for item in (produced_signals.get("evidence") or []) if isinstance(item, dict)],
    )
    for gold_item, produced_item in pairs:
        for dimension in EVIDENCE_RATED:
            name = f"evidence.{dimension}"
            gold_value = _number(gold_item.get(dimension))
            produced_value = _number(produced_item.get(dimension))
            if gold_value is None:
                continue
            if produced_value is None:
                unrated.append(f"{name} (unrated by the model)")
                continue
            deviations.append(
                (abs(produced_value - gold_value), name, f"{name} {gold_value:.2f} -> {produced_value:.2f}")
            )

    deviations.sort(key=lambda row: (-row[0], row[1]))
    beyond = [row for row in deviations if row[0] > tolerance]
    # If nothing exceeds the tolerance, the largest deviation is still the honest
    # thing to name: "all ratings were within tolerance" is itself the explanation.
    chosen = beyond[:limit] if beyond else deviations[:1]
    notes.extend(row[2] for row in chosen)
    notes.extend(sorted(unrated)[:limit])
    return notes


def engine_row(
    signals: dict[str, Any],
    base_config: dict[str, Any],
    scenario_id: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one packet through the engine harness's own code path.

    ``run_scenario`` is reused rather than re-implemented: it merges
    ``config_overrides`` over the base config, checks config semantics, builds the
    detection and builds the evaluation only when ``next_action`` is
    ``auto_evaluate``. Re-implementing that here would be a second definition of the
    production loop, and the two would drift.
    """
    return run_scenario(
        {
            "scenario_id": scenario_id,
            "signals": signals,
            "config_overrides": overrides or {},
            "expect": {},
        },
        base_config,
    )


def score_pair(
    scenario: dict[str, Any],
    produced_packet: dict[str, Any],
    base_config: dict[str, Any],
) -> dict[str, Any]:
    """Score one produced packet against its gold scenario."""
    scenario_id = scenario["scenario_id"]
    overrides = scenario.get("config_overrides") or {}
    gold_signals = scenario.get("signals") or {}

    accumulator, coverage = collect_pairs(gold_signals, produced_packet)
    reference = engine_row(gold_signals, base_config, scenario_id, overrides)
    produced = engine_row(produced_packet, base_config, scenario_id, overrides)
    checks = compare_decisions(reference, produced)

    mismatches: list[dict[str, Any]] = []
    if produced["error"]:
        # Every decision field is already counted as a mismatch by
        # ``compare_decisions``; one traceable row explains all six.
        mismatches.append(
            {
                "scenario_id": scenario_id,
                "field": "engine_error",
                "gold": "engine ran",
                "produced": produced["error"],
                "reason": "engine_error",
                "attribution": attributions(gold_signals, produced_packet),
            }
        )
    else:
        for field in DECISION_FIELDS:
            if checks[field]:
                continue
            mismatches.append(
                {
                    "scenario_id": scenario_id,
                    "field": field,
                    "gold": reference.get(field),
                    "produced": produced.get(field),
                    "reason": "value",
                    "attribution": attributions(gold_signals, produced_packet),
                }
            )

    return {
        "scenario_id": scenario_id,
        "family": scenario.get("family", "unfiled"),
        "annotator": produced_packet.get("annotator"),
        "accumulator": accumulator,
        "coverage": coverage,
        "checks": checks,
        "mismatches": mismatches,
        "reference_error": reference["error"],
        "produced_error": produced["error"],
        "reference": {field: reference.get(field) for field in DECISION_FIELDS},
        "produced": {field: produced.get(field) for field in DECISION_FIELDS},
    }


# --------------------------------------------------------------------------- #
# packet loading and matching
# --------------------------------------------------------------------------- #


def claimed_scenario_id(path: Path, packet: dict[str, Any]) -> str:
    """The id a produced packet claims for itself, for reporting unmatched files."""
    field = packet.get("scenario_id")
    if isinstance(field, str) and field:
        return field
    run_id = packet.get("run_id")
    if isinstance(run_id, str) and run_id.startswith("eval_"):
        return run_id[len("eval_") :]
    return path.stem


def resolve_scenario_id(path: Path, packet: dict[str, Any], gold_ids: set[str]) -> str | None:
    """Which gold scenario a produced packet belongs to, or ``None``.

    The documented collection format is ``<scenario_id>.json``, so the file stem is
    tried first and wins if it names a scenario: a model that writes a drifting
    ``scenario_id`` field inside the packet cannot silently remap itself onto another
    case. The ``scenario_id`` field and the corpus's ``eval_<scenario_id>`` ``run_id``
    convention are accepted as fallbacks for packets collected without renaming.
    """
    stem = path.stem
    if stem in gold_ids:
        return stem
    field = packet.get("scenario_id")
    if isinstance(field, str) and field in gold_ids:
        return field
    run_id = packet.get("run_id")
    if isinstance(run_id, str) and run_id.startswith("eval_") and run_id[len("eval_") :] in gold_ids:
        return run_id[len("eval_") :]
    return None


def strip_collection_keys(packet: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop collection-only keys, returning ``(packet, keys_found)``.

    ``scenario_id`` is how a collected packet names the case it belongs to; the
    schema does not allow it, and rejecting a packet over it would make the
    documented collection format unusable. The keys removed are returned so the
    report can state how many packets used one.
    """
    found = sorted(key for key in packet if key in COLLECTION_KEYS)
    if not found:
        return packet, []
    return {key: value for key, value in packet.items() if key not in COLLECTION_KEYS}, found


def load_packets(directory: Path | None, schema: dict[str, Any], gold_ids: set[str]) -> list[dict[str, Any]]:
    """Read, validate and match every ``*.json`` packet in a directory.

    A malformed or schema-invalid packet is recorded with its validation errors and
    excluded from the metrics rather than aborting the run: a scoring harness that
    crashes on the first bad packet reports nothing about the other fifty-nine, and
    the errors are themselves a perception finding.
    """
    if directory is None or not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            records.append({"file": path.name, "kind": "unreadable", "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if not isinstance(raw, dict):
            records.append({"file": path.name, "kind": "invalid", "errors": ["packet is not a JSON object"]})
            continue
        packet, collection_keys = strip_collection_keys(raw)
        errors = validate(schema, packet)
        if errors:
            records.append({"file": path.name, "kind": "invalid", "errors": errors})
            continue
        scenario_id = resolve_scenario_id(path, packet, gold_ids)
        records.append(
            {
                "file": path.name,
                "kind": "matched" if scenario_id else "unmatched",
                "scenario_id": scenario_id,
                "claimed_id": claimed_scenario_id(path, packet),
                "annotator": packet.get("annotator"),
                "collection_keys": collection_keys,
                "packet": packet,
            }
        )
    return records


# --------------------------------------------------------------------------- #
# corpus-wide scoring
# --------------------------------------------------------------------------- #


def score(
    packets_dir: str | Path | None,
    config: dict[str, Any],
    tolerance: float = DEFAULT_TOLERANCE,
    scenarios: list[dict[str, Any]] | None = None,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score a directory of model-produced packets against the gold corpus."""
    corpus = load_scenarios(SCENARIO_DIR) if scenarios is None else scenarios
    gold_by_id = {scenario["scenario_id"]: scenario for scenario in corpus}
    signals_schema = load_schema("signals") if schema is None else schema

    directory = Path(packets_dir) if packets_dir is not None else None
    records = load_packets(directory, signals_schema, set(gold_by_id))

    invalid = [record for record in records if record["kind"] == "invalid"]
    unreadable = [record for record in records if record["kind"] == "unreadable"]
    unmatched = [record for record in records if record["kind"] == "unmatched"]

    matched: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for record in records:
        if record["kind"] != "matched":
            continue
        scenario_id = record["scenario_id"]
        if scenario_id in matched:
            duplicates.append(record["file"])
            continue
        matched[scenario_id] = record

    accumulator = _empty_accumulator()
    alignment = {
        "gold_items": 0,
        "produced_items": 0,
        "paired": 0,
        "paired_by_id": 0,
        "paired_by_position": 0,
        "gold_unpaired": 0,
        "produced_unpaired": 0,
    }
    per_scenario: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    type_pairs: list[tuple[Any, Any]] = []

    for scenario_id in sorted(matched):
        scenario = gold_by_id[scenario_id]
        result = score_pair(scenario, matched[scenario_id]["packet"], config)
        merge_accumulators(accumulator, result["accumulator"])
        for key, value in result["coverage"].items():
            alignment[key] += value
        per_scenario.append({key: value for key, value in result.items() if key != "accumulator"})
        mismatches.extend(result["mismatches"])
        type_pairs.append(
            (
                _dig(scenario.get("signals") or {}, ("relation", "type")),
                _dig(matched[scenario_id]["packet"], ("relation", "type")),
            )
        )

    rated_scenarios = [entry for entry in per_scenario if not entry["reference_error"]]
    decision_summary = {}
    for field in DECISION_FIELDS:
        agree = sum(1 for entry in rated_scenarios if entry["checks"][field])
        decision_summary[field] = {
            "n": len(rated_scenarios),
            "agreement": _round(agree / len(rated_scenarios)) if rated_scenarios else None,
            "mismatches": len(rated_scenarios) - agree,
        }
    all_agree = sum(1 for entry in rated_scenarios if entry["checks"]["all"])
    decision_summary["all"] = {
        "n": len(rated_scenarios),
        "agreement": _round(all_agree / len(rated_scenarios)) if rated_scenarios else None,
        "mismatches": len(rated_scenarios) - all_agree,
    }

    ratings = {}
    for name in ALL_DIMENSIONS:
        entry = accumulator[name]
        metrics = error_metrics(entry["pairs"], tolerance)
        metrics["produced_unrated"] = entry["produced_unrated"]
        metrics["gold_unrated"] = entry["gold_unrated"]
        ratings[name] = metrics

    annotators = sorted(
        {
            record["annotator"]
            for record in records
            if record["kind"] == "matched" and isinstance(record.get("annotator"), str)
        }
    )

    annotated = [record for record in records if record["kind"] in ("matched", "unmatched")]
    with_collection_keys = sum(1 for record in annotated if record.get("collection_keys"))
    missing = sorted(set(gold_by_id) - set(matched))
    scored = bool(rated_scenarios)

    return {
        # ``as_posix`` so a repo-relative directory reads identically in a report
        # generated on Windows and one generated on Linux.
        "packets_dir": directory.as_posix() if directory is not None else None,
        "packets_dir_exists": bool(directory is not None and directory.exists()),
        "scored": scored,
        "tolerance": tolerance,
        "annotators": annotators,
        "gold_total": len(gold_by_id),
        "counts": {
            "files": len(records),
            "valid": len(records) - len(invalid) - len(unreadable),
            "invalid": len(invalid),
            "unreadable": len(unreadable),
            "matched": len(matched),
            "scored": len(rated_scenarios),
            "unmatched": len(unmatched),
            "missing": len(missing),
            "duplicate": len(duplicates),
            "with_collection_keys": with_collection_keys,
        },
        "invalid": [{"file": record["file"], "errors": record["errors"]} for record in invalid],
        "unreadable": [
            {"file": record["file"], "detail": record["detail"]} for record in unreadable
        ],
        "unmatched": [
            {"file": record["file"], "claimed_id": record["claimed_id"]} for record in unmatched
        ],
        "duplicates": sorted(duplicates),
        "missing": missing,
        "reference_errors": [
            {"scenario_id": entry["scenario_id"], "error": entry["reference_error"]}
            for entry in per_scenario
            if entry["reference_error"]
        ],
        "ratings": {name: ratings[name] for name in SCALAR_DIMENSIONS},
        "evidence_ratings": {name: ratings[name] for name in EVIDENCE_DIMENSIONS},
        "evidence_alignment": alignment,
        "categorical": {"relation.type": categorical_agreement(type_pairs)},
        "decisions": decision_summary,
        "config_hash": config_hash(config),
        "matches": mismatches,
        "per_scenario": per_scenario,
    }


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def _caveat_lines() -> list[str]:
    """The honesty block, mirroring ``run_scenarios.py``'s caveat in the report."""
    return [
        "> **What this number cannot show.** It measures agreement between the packets a",
        "> model produced and the packets a human annotator wrote for the same",
        "> conversation. It cannot show that the gold annotations are correct: a packet",
        "> that reproduces a mis-annotated gold packet scores perfectly, and one that is",
        "> right where the annotator was wrong is penalised. It does not measure reply",
        "> quality — a packet can match gold exactly and the reply built from it can",
        "> still be unhelpful, sycophantic or wrong. It cannot separate \"the model rates",
        "> differently\" from \"the codebook is ambiguous\": low agreement on a dimension is",
        "> a finding about the construct as much as about the model, which is why",
        "> agreement is reported per dimension rather than pooled. And decision agreement",
        "> is measured against the gold packet run through the same engine, not against",
        "> the corpus `expect` block, so it isolates packet error from engine error;",
        "> `scripts/run_scenarios.py --strict` is what pins the engine to `expect`.",
    ]


def _protocol_lines() -> list[str]:
    return [
        "## Packet collection protocol",
        "",
        "Until packets exist there is no perception measurement, and `docs/design-rationale.md`",
        "describes exactly this state: the protocol is specified, the harness exists, and the",
        "number has not been produced.",
        "",
        "For each scenario under `eval/scenarios/`:",
        "",
        "1. Put the scenario's raw conversation in front of the host model with",
        "   [`../references/prompts/detect.md`](../references/prompts/detect.md) and the anchored",
        "   rubric in [`../references/codebook.md`](../references/codebook.md).",
        "2. Do not show the model the gold packet or the scenario's `expect` block; the gold",
        "   packet is the answer key.",
        "3. Save the returned packet as `<packets_dir>/<scenario_id>.json`, one file per",
        "   scenario, with `<scenario_id>` equal to the scenario's file stem. A `scenario_id`",
        "   field and the corpus's `eval_<scenario_id>` `run_id` convention are accepted as",
        "   fallbacks, but the file name wins when the two disagree; a `scenario_id` key is",
        "   stripped before schema validation, since the packet schema forbids it.",
        "4. Set `annotator` to the model id (for example `annotator: \"deepseek-v4-flash\"`), so",
        "   the report can name what produced the packets and model-generated packets are",
        "   never confused with `gold` ones.",
        "5. Collect one packet per scenario per model. Multiple models can be scored by",
        "   running the harness once per directory.",
        "",
        "Then run:",
        "",
        "```",
        "python scripts/score_signals.py --packets <packets_dir> --write-report",
        "```",
        "",
        "## What will be reported",
        "",
        "| section | contents |",
        "|---|---|",
        "| Coverage | files supplied, valid / invalid / unreadable, matched, unmatched, gold scenarios with no packet |",
        "| Rating agreement | per dimension: n, MAE, RMSE, bias (model minus gold), rate within tolerance, ratings the model left unrated |",
        "| Categorical agreement | `relation.type` agreement with the confusion pairs |",
        "| Evidence alignment | how many items were paired by id and how many positionally |",
        "| Decision agreement | level, channel, conflict_type, gate, `next_action`, strategy, plus the all-fields rate |",
        "| Attribution | every mismatched decision with the dimension(s) the packet deviated on most |",
        "",
        "## Dimension reference",
        "",
        "Every rated dimension below has anchors in `references/codebook.md`; the 0.00 and 1.00",
        "anchors are restated here because they define what \"right\" means in the tables above.",
        "",
        "| dimension | 0.00 anchor vs 1.00 anchor |",
        "|---|---|",
    ]


def _coverage_lines(result: dict[str, Any]) -> list[str]:
    counts = result["counts"]
    if counts["files"] == 0:
        # Nothing was supplied, so there is no coverage to enumerate and listing
        # every gold scenario would make an empty report look like a measurement.
        if result["packets_dir"] is None:
            source = "- no packet directory was supplied (`--packets` was not given)"
        elif not result["packets_dir_exists"]:
            source = f"- the packet directory `{result['packets_dir']}` does not exist"
        else:
            source = f"- the packet directory `{result['packets_dir']}` contains no `*.json` files"
        return ["## Coverage", "", source, "- packet files read: 0", "- gold scenarios covered: 0", ""]

    lines = [
        "## Coverage",
        "",
        f"- packet files read: {counts['files']}",
        f"- schema-valid: {counts['valid']} ({counts['invalid']} invalid, {counts['unreadable']} unreadable)",
        f"- matched to a gold scenario: {counts['matched']}",
        f"- scored: {counts['scored']} (the rest had a gold reference that failed to run)",
        f"- gold scenarios with no packet: {counts['missing']} of {result['gold_total']}",
        f"- produced packets with no matching scenario: {counts['unmatched']}",
        f"- duplicate packets ignored: {counts['duplicate']}",
        "",
    ]
    if counts["with_collection_keys"]:
        lines += [
            f"{counts['with_collection_keys']} packets carried a collection key the packet schema does not",
            "allow (`scenario_id`). It is stripped before schema validation and is never passed to the",
            "engine, so it cannot change a rating or a decision.",
            "",
        ]
    if result["missing"]:
        shown = ", ".join(f"`{name}`" for name in result["missing"][:20])
        more = "" if len(result["missing"]) <= 20 else f", and {len(result['missing']) - 20} more"
        lines += [f"Missing coverage: {shown}{more}.", ""]
    if result["unmatched"]:
        lines += ["Unmatched files:", ""]
        lines += [f"- `{entry['file']}` claims `{entry['claimed_id']}`" for entry in result["unmatched"]]
        lines.append("")
    if result["invalid"]:
        lines += ["Invalid packets (excluded from every metric above):", ""]
        for entry in result["invalid"]:
            detail = "; ".join(entry["errors"][:3])
            lines.append(f"- `{entry['file']}`: {detail}")
        lines.append("")
    if result["unreadable"]:
        lines += ["Unreadable files:", ""]
        lines += [f"- `{entry['file']}`: {entry['detail']}" for entry in result["unreadable"]]
        lines.append("")
    if result["duplicates"]:
        lines += [f"Duplicates ignored (first file in sorted order wins): {', '.join(f'`{n}`' for n in result['duplicates'])}.", ""]
    if result["reference_errors"]:
        lines += ["Gold references that failed to run (excluded from decision agreement):", ""]
        lines += [f"- `{entry['scenario_id']}`: {entry['error']}" for entry in result["reference_errors"]]
        lines.append("")
    return lines


def write_report(result: dict[str, Any], path: Path = REPORT_PATH, stamp: str | None = None) -> Path:
    """Write ``eval/perception.md``.

    With no packets the report says so in words and documents the protocol, rather
    than emitting empty tables that read like a measurement of zero. With packets it
    reports the tables and keeps the caveat block above them.
    """
    lines = [
        "# Perception report",
        "",
        "Generated by `python scripts/score_signals.py --write-report`.",
        "",
    ]
    if stamp:
        lines += [f"- generated at: {stamp} (non-deterministic; excluded from the reproducibility check)", ""]
    lines += _caveat_lines()
    lines.append("")

    if not result["scored"]:
        supplied = result["packets_dir"]
        lines += [
            "## Status: not yet run",
            "",
            (
                "No model-produced packets were scored, so there is no perception number "
                "in this report."
            ),
            (
                f"Packet source: `{supplied}`."
                if supplied
                else "Packet source: none supplied (`--packets` was not given)."
            ),
            "",
            "This is the state `docs/design-rationale.md` describes: perception is a separate,",
            "measurable quantity and the harness that measures it exists, but no model has been",
            "run over the corpus yet. The engine half of the corpus is verified on every commit",
            "by `scripts/run_scenarios.py --strict`; this file will stay empty until packets are",
            "collected, and empty tables would be a worse artifact than this paragraph because",
            "they would read as a measurement.",
            "",
        ]
        if supplied and result["counts"]["files"]:
            lines += [
                f"Files were found and read ({result['counts']['files']}), but none could be",
                "scored: an invalid packet, an unmatched packet and a gold reference that fails",
                "to run are all reported below with their reasons.",
                "",
            ]
        else:
            lines += [
                "The harness exits 0 in this state on purpose: CI runs on a repository with no",
                "model packets, and a missing measurement must not fail the build.",
                "",
            ]
        lines += _coverage_lines(result)
        lines += _protocol_lines()
        for name in ALL_DIMENSIONS:
            lines.append(f"| `{name}` | {DIMENSION_ANCHORS[name]} |")
        lines.append("")
        write_text(path, "\n".join(lines))
        return path

    lines += [
        f"- packets directory: `{result['packets_dir']}`",
        f"- produced by: {', '.join(f'`{name}`' for name in result['annotators']) or '`annotator` not set'}",
        f"- exact-agreement tolerance: ±{result['tolerance']:.3f}",
        f"- base config hash: `{result['config_hash']}`",
        f"- gold scenarios: {result['gold_total']}",
        f"- packets scored: {result['counts']['scored']}",
        "",
        "## Rating agreement per dimension",
        "",
        "`bias` is the mean signed error (model minus gold), so a positive value means the",
        "model rates the field higher than the annotator did; a large bias with a small MAE is",
        "a calibration finding rather than noise. `within` counts ratings inside the tolerance",
        "band above. `unrated by model` counts fields the annotator rated and the model did",
        "not, which is not a small error: the evaluator renormalises weights over the",
        "dimensions that are present, so a missing rating changes the evidence score.",
        "",
        "| dimension | n | MAE | RMSE | bias | within | unrated by model |",
        "|---|---|---|---|---|---|---|",
    ]

    def rating_row(name: str, metrics: dict[str, Any]) -> str:
        return (
            f"| `{name}` | {metrics['n']} | {_fmt(metrics['mae'])} | {_fmt(metrics['rmse'])} | "
            f"{_fmt_signed(metrics['bias'])} | {_fmt(metrics['exact_agreement'])} | "
            f"{metrics['produced_unrated']} |"
        )

    lines += [rating_row(name, result["ratings"][name]) for name in SCALAR_DIMENSIONS]
    lines += ["", "### Per evidence item", ""]
    lines += ["| dimension | n | MAE | RMSE | bias | within | unrated by model |", "|---|---|---|---|---|---|---|"]
    lines += [rating_row(name, result["evidence_ratings"][name]) for name in EVIDENCE_DIMENSIONS]

    alignment = result["evidence_alignment"]
    lines += [
        "",
        "### Evidence alignment",
        "",
        f"{alignment['paired']} item pairs compared ({alignment['paired_by_id']} by id,",
        f"{alignment['paired_by_position']} positionally); {alignment['gold_unpaired']} gold items and",
        f"{alignment['produced_unpaired']} produced items had no counterpart. Positional pairing is",
        "weaker evidence than an id match, because it assumes the model listed the same items in the",
        "same order.",
        "",
        "## Categorical agreement",
        "",
        "| field | n | agreement | confusions (gold -> produced) |",
        "|---|---|---|---|",
    ]
    for name, metrics in result["categorical"].items():
        confusions = ", ".join(
            f"`{item['gold']}` -> `{item['produced']}` ({item['count']})" for item in metrics["confusions"]
        )
        lines.append(f"| `{name}` | {metrics['n']} | {_fmt(metrics['agreement'])} | {confusions or 'none'} |")

    lines += [
        "",
        "## Downstream decision agreement",
        "",
        "Each packet — produced and gold — is run through the engine harness's own code path",
        "(`run_scenarios.run_scenario`), so a mismatch below is attributable to the packet and",
        "not to the arithmetic. `strategy` is compared only where both packets route: a",
        "perception error that pushes a conflict below the alert threshold means the router",
        "never runs, and there is no strategy to agree about.",
        "",
        "| decision | n | agreement | mismatches |",
        "|---|---|---|---|",
    ]
    for field in list(DECISION_FIELDS) + ["all"]:
        metrics = result["decisions"][field]
        label = "**all fields**" if field == "all" else f"`{field}`"
        lines.append(f"| {label} | {metrics['n']} | {_fmt(metrics['agreement'])} | {metrics['mismatches']} |")

    lines += [
        "",
        f"## Attribution ({len(result['matches'])} mismatched decisions)",
        "",
        "The right-hand column names the dimensions the produced packet deviated on most, so a",
        "decision error is traceable to a rating rather than to a label.",
        "",
    ]
    if result["matches"]:
        lines += ["| scenario | decision | gold | produced | largest rating deviations |", "|---|---|---|---|---|"]
        for entry in result["matches"]:
            attribution = "; ".join(entry["attribution"]) or "no rated deviation above tolerance"
            lines.append(
                f"| `{entry['scenario_id']}` | {entry['field']} | {_fmt(entry['gold'])} | "
                f"{_fmt(entry['produced'])} | {attribution} |"
            )
        lines.append("")
    else:
        lines += ["None.", ""]

    lines += _coverage_lines(result)
    lines.append("")

    write_text(path, "\n".join(lines))
    return path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def print_summary(result: dict[str, Any]) -> None:
    if not result["scored"]:
        print("nothing to score: no model-produced packets were supplied")
        if result["packets_dir"] is not None:
            print(f"  packet directory: {result['packets_dir']}")
        counts = result["counts"]
        if counts["files"]:
            print(
                f"  files read: {counts['files']} "
                f"({counts['invalid']} invalid, {counts['unreadable']} unreadable, "
                f"{counts['unmatched']} unmatched, {counts['matched']} matched)"
            )
        print("  supply --packets <dir> to measure perception; see eval/perception.md")
        return

    counts = result["counts"]
    print(f"gold scenarios   {result['gold_total']}")
    print(f"packets          {counts['valid']} valid, {counts['invalid']} invalid, {counts['unreadable']} unreadable")
    print(f"matched          {counts['matched']} scored, {counts['missing']} gold scenarios uncovered")
    if counts["unmatched"] or counts["duplicate"]:
        print(f"unmatched        {counts['unmatched']} ({counts['duplicate']} duplicate files ignored)")
    print(f"tolerance        ±{result['tolerance']:.3f}")
    print()
    print("What this number is: agreement between the packets a model produced and")
    print("the gold packets a human annotator wrote. What it is NOT: evidence that the")
    print("gold packets are correct, nor that replies built from them are any good.")
    print("Rating agreement answers 'did perception land where the codebook says?';")
    print("decision agreement answers 'did that difference matter?'. The second is the")
    print("number a reviewer asks for, and the attribution table is why it is credible.")
    print()
    print("rating dimension                           n    MAE    RMSE     bias   within")
    print("-----------------------------------------  ---  -----  ------  -------  -------")
    for name in ALL_DIMENSIONS:
        metrics = result["ratings"].get(name) or result["evidence_ratings"][name]
        print(
            f"{name:<41}  {metrics['n']:>3}  {_fmt(metrics['mae'])}  {_fmt(metrics['rmse'])}  "
            f"{_fmt_signed(metrics['bias']):>7}  {_fmt(metrics['exact_agreement'])}"
        )
    print()
    categorical = result["categorical"]["relation.type"]
    print("categorical          n   agreement")
    print("-----------------  ---  ----------")
    print(f"relation.type      {categorical['n']:>3}  {_fmt(categorical['agreement'])}")
    print()
    print("decision               n   agreement   mismatches")
    print("-------------------  ---  ----------  -----------")
    for field in list(DECISION_FIELDS) + ["all"]:
        metrics = result["decisions"][field]
        print(f"{field:<19}  {metrics['n']:>3}  {_fmt(metrics['agreement']):>10}  {metrics['mismatches']:>11}")

    if result["matches"]:
        print()
        print(f"mismatched decisions ({len(result['matches'])}):")
        for entry in result["matches"][:40]:
            attribution = "; ".join(entry["attribution"]) or "no rated deviation above tolerance"
            print(
                f"  - {entry['scenario_id']} {entry['field']}: gold {_fmt(entry['gold'])} -> "
                f"produced {_fmt(entry['produced'])} [{attribution}]"
            )
        if len(result["matches"]) > 40:
            print(f"  ... and {len(result['matches']) - 40} more (see eval/perception.md)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packets", help="directory of model-produced packets, one <scenario_id>.json per scenario")
    parser.add_argument("--config", help="base config to merge scenario overrides onto")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="absolute tolerance for exact agreement (default 0.05)")
    parser.add_argument("--strict", action="store_true", help="exit non-zero on any decision-level mismatch")
    parser.add_argument("--write-report", action="store_true", help="write eval/perception.md")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON instead of a table")
    parser.add_argument("--stamp", metavar="ISO8601", help="optional timestamp recorded in the report, clearly marked as non-deterministic")
    args = parser.parse_args(argv)

    if args.tolerance < 0:
        parser.error("--tolerance must be >= 0")

    config = load_config(args.config)
    result = score(args.packets, config, args.tolerance)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print_summary(result)

    if args.write_report:
        written = write_report(result, stamp=args.stamp)
        # In --json mode the note goes to stderr, so stdout stays parseable.
        print(f"wrote {written}", file=sys.stderr if args.json else sys.stdout)

    if args.strict and result["scored"] and result["decisions"]["all"]["mismatches"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
