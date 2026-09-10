"""Tests for the perception scorer: metrics, matching, decisions and the report.

These tests deliberately derive their expectations from the corpus and the engine at
run time rather than hard-coding gold labels, tension values or strategy names. The
corpus and the config are research instruments that move; a test that pins `s01` to
`alert` would fail on a legitimate corpus edit and would say nothing about the
scorer.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import sys
import unittest
from pathlib import Path

# ``context`` lives beside this file and is importable under
# ``unittest discover -s tests -t tests`` (which puts tests/ on the path) but not
# under ``python -m unittest tests.test_score_signals`` from the repository root.
# Adding the directory here keeps both invocations working without touching the
# shared bootstrap.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import context  # noqa: E402
from cds_config import write_text  # noqa: E402

import score_signals as scorer  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


def gold_scenarios():
    """The shipped corpus, loaded the way the harness loads it."""
    scenarios = scorer.load_scenarios(scorer.SCENARIO_DIR)
    assert scenarios, "the evaluation corpus must exist for these tests"
    return scenarios


def engine_row(scenario):
    """The engine's decision row for a scenario's gold packet."""
    return scorer.engine_row(
        scenario["signals"],
        context.BASE_CONFIG,
        scenario["scenario_id"],
        scenario.get("config_overrides"),
    )


def firing_scenario(scenarios=None):
    """A scenario the engine reports as alert or high, derived rather than named."""
    for scenario in scenarios if scenarios is not None else gold_scenarios():
        row = engine_row(scenario)
        if not row["error"] and row["level"] in ("alert", "high"):
            return scenario
    raise AssertionError("the corpus must contain at least one firing scenario")


def conflict_free_packet(packet):
    """The same packet, but one that perceives no conflict and no indeterminacy."""
    packet = copy.deepcopy(packet)
    packet["relation"]["type"] = "none"
    packet["evidence_conflict_unresolved"] = 0.0
    return packet


def write_packet(directory, name, packet):
    path = Path(directory) / f"{name}.json"
    write_text(path, json.dumps(packet, ensure_ascii=False, indent=2))
    return path


def write_packets(directory, packets):
    for name, packet in packets.items():
        write_packet(directory, name, packet)


def write_gold_packets(directory, scenarios):
    for scenario in scenarios:
        write_packet(directory, scenario["scenario_id"], copy.deepcopy(scenario["signals"]))


def synthetic_scenario(scenario_id="syn_001", config_overrides=None, **signal_overrides):
    """A one-scenario corpus that does not depend on the shipped eval corpus."""
    packet = context.base_packet()
    for key, value in signal_overrides.items():
        if isinstance(value, dict) and isinstance(packet.get(key), dict):
            packet[key].update(value)
        else:
            packet[key] = copy.deepcopy(value)
    return {
        "scenario_id": scenario_id,
        "family": "synthetic",
        "config_overrides": config_overrides or {},
        "signals": packet,
        "expect": {},
    }


def run_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = scorer.main(argv)
    return code, out.getvalue()


# --------------------------------------------------------------------------- #
# metric arithmetic
# --------------------------------------------------------------------------- #


class TestErrorMetrics(unittest.TestCase):
    """Hand-computed fixtures, so the arithmetic is checked and not just exercised."""

    PAIRS = [(0.0, 0.1), (0.5, 0.5), (1.0, 0.6)]

    def test_mae_is_the_mean_absolute_error(self):
        # |0.1| + |0.0| + |-0.4| = 0.5, over 3 pairs
        self.assertAlmostEqual(scorer.error_metrics(self.PAIRS)["mae"], 0.5 / 3, places=6)

    def test_rmse_is_the_root_mean_squared_error(self):
        # sqrt((0.01 + 0.0 + 0.16) / 3)
        self.assertAlmostEqual(scorer.error_metrics(self.PAIRS)["rmse"], (0.17 / 3) ** 0.5, places=6)

    def test_bias_is_the_mean_signed_error_model_minus_gold(self):
        # (0.1 + 0.0 - 0.4) / 3 = -0.1: the model under-rates on balance
        self.assertAlmostEqual(scorer.error_metrics(self.PAIRS)["bias"], -0.1, places=6)

    def test_bias_is_positive_when_the_model_over_rates(self):
        self.assertAlmostEqual(scorer.error_metrics([(0.2, 0.6), (0.4, 0.6)])["bias"], 0.3, places=6)

    def test_bias_can_be_zero_while_the_mae_is_large(self):
        metrics = scorer.error_metrics([(0.0, 0.4), (0.4, 0.0)])
        self.assertAlmostEqual(metrics["bias"], 0.0, places=9)
        self.assertAlmostEqual(metrics["mae"], 0.4, places=9)

    def test_rmse_exceeds_the_mae_when_errors_differ_in_size(self):
        metrics = scorer.error_metrics([(0.0, 0.05), (0.0, 0.05), (0.0, 0.9)])
        self.assertGreater(metrics["rmse"], metrics["mae"])

    def test_rmse_equals_the_mae_when_every_error_is_the_same(self):
        metrics = scorer.error_metrics([(0.0, 0.1), (0.5, 0.6), (0.9, 1.0)])
        self.assertAlmostEqual(metrics["rmse"], metrics["mae"], places=9)

    def test_max_abs_error_is_reported(self):
        self.assertAlmostEqual(scorer.error_metrics(self.PAIRS)["max_abs_error"], 0.4, places=9)

    def test_pair_count_is_reported(self):
        self.assertEqual(scorer.error_metrics(self.PAIRS)["n"], 3)

    def test_empty_pairs_are_not_a_perfect_score(self):
        """No comparable rating is missing data, not agreement at zero error."""
        metrics = scorer.error_metrics([])
        self.assertEqual(metrics["n"], 0)
        self.assertIsNone(metrics["mae"])
        self.assertIsNone(metrics["rmse"])
        self.assertIsNone(metrics["bias"])
        self.assertIsNone(metrics["exact_agreement"])


class TestToleranceAgreement(unittest.TestCase):
    def test_agreement_counts_only_pairs_inside_the_tolerance(self):
        metrics = scorer.error_metrics([(0.0, 0.04), (0.5, 0.60)], tolerance=0.05)
        self.assertEqual(metrics["within_tolerance"], 1)
        self.assertAlmostEqual(metrics["exact_agreement"], 0.5, places=9)

    def test_tolerance_is_inclusive_at_the_boundary(self):
        metrics = scorer.error_metrics([(0.0, 0.05)], tolerance=0.05)
        self.assertAlmostEqual(metrics["exact_agreement"], 1.0, places=9)

    def test_a_difference_just_outside_the_tolerance_does_not_count(self):
        metrics = scorer.error_metrics([(0.0, 0.050001)], tolerance=0.05)
        self.assertAlmostEqual(metrics["exact_agreement"], 0.0, places=9)

    def test_the_sign_of_the_difference_is_irrelevant_to_agreement(self):
        metrics = scorer.error_metrics([(0.60, 0.55)], tolerance=0.05)
        self.assertAlmostEqual(metrics["exact_agreement"], 1.0, places=9)

    def test_zero_tolerance_counts_only_exact_matches(self):
        metrics = scorer.error_metrics([(0.5, 0.5), (0.5, 0.5000001)], tolerance=0.0)
        self.assertEqual(metrics["within_tolerance"], 1)

    def test_a_wider_tolerance_can_only_raise_agreement(self):
        pairs = [(0.0, 0.04), (0.2, 0.30), (0.6, 0.85)]
        narrow = scorer.error_metrics(pairs, tolerance=0.05)["exact_agreement"]
        wide = scorer.error_metrics(pairs, tolerance=0.30)["exact_agreement"]
        self.assertLessEqual(narrow, wide)

    def test_tolerance_does_not_change_the_mae(self):
        pairs = [(0.0, 0.04), (0.2, 0.30)]
        self.assertEqual(
            scorer.error_metrics(pairs, tolerance=0.01)["mae"],
            scorer.error_metrics(pairs, tolerance=0.50)["mae"],
        )


class TestCategoricalAgreement(unittest.TestCase):
    def test_agreement_rate_over_categories(self):
        metrics = scorer.categorical_agreement([("a", "a"), ("a", "b"), ("b", "b"), ("b", "b")])
        self.assertEqual(metrics["n"], 4)
        self.assertAlmostEqual(metrics["agreement"], 0.75, places=9)

    def test_confusions_are_reported_with_counts(self):
        metrics = scorer.categorical_agreement(
            [("none", "evidence_vs_stance"), ("none", "evidence_vs_stance"), ("a", "a")]
        )
        self.assertEqual(len(metrics["confusions"]), 1)
        confusion = metrics["confusions"][0]
        self.assertEqual(confusion["gold"], "none")
        self.assertEqual(confusion["produced"], "evidence_vs_stance")
        self.assertEqual(confusion["count"], 2)

    def test_confusions_are_sorted_deterministically(self):
        metrics = scorer.categorical_agreement([("a", "b"), ("a", "c"), ("a", "c")])
        self.assertEqual([item["produced"] for item in metrics["confusions"]], ["c", "b"])

    def test_perfect_agreement_has_no_confusions(self):
        metrics = scorer.categorical_agreement([("x", "x"), ("y", "y")])
        self.assertEqual(metrics["confusions"], [])
        self.assertAlmostEqual(metrics["agreement"], 1.0, places=9)

    def test_empty_input_is_not_agreement(self):
        metrics = scorer.categorical_agreement([])
        self.assertEqual(metrics["n"], 0)
        self.assertIsNone(metrics["agreement"])


# --------------------------------------------------------------------------- #
# evidence alignment
# --------------------------------------------------------------------------- #


class TestPairEvidence(unittest.TestCase):
    @staticmethod
    def item(item_id, **claims):
        return {"id": item_id, "claim": claims.pop("claim", item_id), **claims}

    def test_items_pair_by_id_even_when_the_order_differs(self):
        gold = [self.item("a"), self.item("b")]
        produced = [self.item("b"), self.item("a")]
        pairs, coverage = scorer.pair_evidence(gold, produced)
        self.assertEqual([(g["id"], p["id"]) for g, p in pairs], [("a", "a"), ("b", "b")])
        self.assertEqual(coverage["paired_by_id"], 2)
        self.assertEqual(coverage["paired_by_position"], 0)

    def test_unknown_ids_fall_back_to_position(self):
        gold = [self.item("ev_s01_a"), self.item("ev_s01_b")]
        produced = [self.item("ev_1"), self.item("ev_2")]
        pairs, coverage = scorer.pair_evidence(gold, produced)
        self.assertEqual([p["id"] for _, p in pairs], ["ev_1", "ev_2"])
        self.assertEqual(coverage["paired_by_position"], 2)
        self.assertEqual(coverage["paired_by_id"], 0)

    def test_id_pairs_are_taken_first_and_the_rest_positionally(self):
        gold = [self.item("a"), self.item("b"), self.item("c")]
        produced = [self.item("c"), self.item("x"), self.item("y")]
        pairs, coverage = scorer.pair_evidence(gold, produced)
        self.assertEqual((pairs[0][0]["id"], pairs[0][1]["id"]), ("c", "c"))
        self.assertEqual(coverage["paired_by_id"], 1)
        self.assertEqual(coverage["paired_by_position"], 2)
        self.assertEqual(coverage["paired"], 3)

    def test_a_short_produced_list_leaves_gold_items_unpaired(self):
        gold = [self.item("a"), self.item("b"), self.item("c")]
        produced = [self.item("a")]
        _, coverage = scorer.pair_evidence(gold, produced)
        self.assertEqual(coverage["paired"], 1)
        self.assertEqual(coverage["gold_unpaired"], 2)
        self.assertEqual(coverage["produced_unpaired"], 0)

    def test_a_long_produced_list_leaves_produced_items_unpaired(self):
        gold = [self.item("a")]
        produced = [self.item("a"), self.item("b"), self.item("c")]
        _, coverage = scorer.pair_evidence(gold, produced)
        self.assertEqual(coverage["paired"], 1)
        self.assertEqual(coverage["produced_unpaired"], 2)

    def test_no_evidence_on_either_side_pairs_nothing(self):
        pairs, coverage = scorer.pair_evidence([], [])
        self.assertEqual(pairs, [])
        self.assertEqual(coverage["paired"], 0)

    def test_duplicate_ids_do_not_pair_one_produced_item_twice(self):
        gold = [self.item("a"), self.item("a")]
        produced = [self.item("a")]
        _, coverage = scorer.pair_evidence(gold, produced)
        self.assertEqual(coverage["paired"], 1)
        self.assertEqual(coverage["gold_unpaired"], 1)


# --------------------------------------------------------------------------- #
# pair collection
# --------------------------------------------------------------------------- #


class TestCollectPairs(unittest.TestCase):
    def test_scalar_ratings_are_collected(self):
        gold = context.base_packet(relation={"opposition": 0.8, "specificity": 0.6})
        produced = context.base_packet(relation={"opposition": 0.4, "specificity": 0.6})
        accumulator, _ = scorer.collect_pairs(gold, produced)
        self.assertEqual(accumulator["relation.opposition"]["pairs"], [(0.8, 0.4)])
        self.assertEqual(accumulator["relation.specificity"]["pairs"], [(0.6, 0.6)])

    def test_a_dimension_the_model_left_unrated_is_counted_not_scored(self):
        gold = context.base_packet()
        produced = context.base_packet()
        del produced["stance"]["confidence"]
        accumulator, _ = scorer.collect_pairs(gold, produced)
        self.assertEqual(accumulator["stance.confidence"]["pairs"], [])
        self.assertEqual(accumulator["stance.confidence"]["produced_unrated"], 1)

    def test_a_dimension_the_annotator_left_unrated_is_not_punished(self):
        gold = context.base_packet()
        del gold["stance"]["confidence"]
        produced = context.base_packet()
        accumulator, _ = scorer.collect_pairs(gold, produced)
        self.assertEqual(accumulator["stance.confidence"]["pairs"], [])
        self.assertEqual(accumulator["stance.confidence"]["gold_unrated"], 1)
        self.assertEqual(accumulator["stance.confidence"]["produced_unrated"], 0)

    def test_dimensions_absent_on_both_sides_are_neither_scored_nor_counted(self):
        gold = context.base_packet()
        produced = context.base_packet()
        for packet in (gold, produced):
            del packet["perception"]
        accumulator, _ = scorer.collect_pairs(gold, produced)
        entry = accumulator["perception.confidence"]
        self.assertEqual((entry["pairs"], entry["produced_unrated"], entry["gold_unrated"]), ([], 0, 0))

    def test_evidence_dimensions_are_pooled_over_items(self):
        gold = context.base_packet()
        produced = context.base_packet()
        second = copy.deepcopy(gold["evidence"][0])
        second["id"] = "ev_002"
        second["credibility"] = 0.8
        gold["evidence"].append(second)
        second_produced = copy.deepcopy(second)
        second_produced["credibility"] = 0.6
        produced["evidence"].append(second_produced)
        accumulator, coverage = scorer.collect_pairs(gold, produced)
        self.assertEqual(len(accumulator["evidence.credibility"]["pairs"]), 2)
        self.assertEqual(coverage["paired_by_id"], 2)

    def test_every_rated_dimension_has_an_accumulator_entry(self):
        accumulator, _ = scorer.collect_pairs(context.base_packet(), context.base_packet())
        self.assertEqual(set(accumulator), set(scorer.ALL_DIMENSIONS))


# --------------------------------------------------------------------------- #
# attribution
# --------------------------------------------------------------------------- #


class TestAttributions(unittest.TestCase):
    def test_the_largest_deviation_is_named_first(self):
        gold = context.base_packet(relation={"opposition": 0.9})
        produced = context.base_packet(relation={"opposition": 0.1})
        notes = scorer.attributions(gold, produced)
        self.assertTrue(notes)
        self.assertTrue(notes[0].startswith("relation.opposition"), notes)

    def test_a_changed_relation_type_is_reported_first(self):
        gold = context.base_packet(relation={"type": "evidence_vs_stance"})
        produced = context.base_packet(relation={"type": "none", "opposition": 0.0})
        notes = scorer.attributions(gold, produced)
        self.assertIn("relation.type evidence_vs_stance -> none", notes)

    def test_an_identical_packet_names_its_largest_deviation(self):
        gold = context.base_packet()
        produced = context.base_packet(relation={"opposition": 0.82})
        notes = scorer.attributions(gold, produced, tolerance=0.05)
        self.assertEqual(len(notes), 1)
        self.assertIn("relation.opposition", notes[0])

    def test_a_dimension_the_model_did_not_rate_is_named(self):
        gold = context.base_packet()
        produced = context.base_packet()
        del produced["evidence"][0]["credibility"]
        notes = scorer.attributions(gold, produced)
        self.assertTrue(any("evidence.credibility" in note and "unrated" in note for note in notes), notes)

    def test_deviations_within_tolerance_are_not_named_when_larger_ones_exist(self):
        gold = context.base_packet(relation={"opposition": 0.9, "specificity": 0.5})
        produced = context.base_packet(relation={"opposition": 0.1, "specificity": 0.52})
        notes = scorer.attributions(gold, produced, tolerance=0.05)
        self.assertTrue(any("relation.opposition" in note for note in notes))
        self.assertFalse(any("relation.specificity" in note for note in notes))


# --------------------------------------------------------------------------- #
# matching produced packets to gold scenarios
# --------------------------------------------------------------------------- #


class TestMatching(unittest.TestCase):
    def test_filename_resolves_to_the_matching_scenario(self):
        packet = context.base_packet()
        self.assertEqual(scorer.resolve_scenario_id(Path("s01_case.json"), packet, {"s01_case"}), "s01_case")

    def test_scenario_id_field_is_a_fallback(self):
        packet = context.base_packet()
        packet["scenario_id"] = "s07_case"
        self.assertEqual(
            scorer.resolve_scenario_id(Path("model_output_3.json"), packet, {"s07_case"}), "s07_case"
        )

    def test_run_id_convention_is_a_fallback(self):
        packet = context.base_packet(run_id="eval_s09_case")
        self.assertEqual(scorer.resolve_scenario_id(Path("packet_9.json"), packet, {"s09_case"}), "s09_case")

    def test_the_filename_wins_over_a_conflicting_field(self):
        packet = context.base_packet()
        packet["scenario_id"] = "s02_other"
        resolved = scorer.resolve_scenario_id(Path("s01_case.json"), packet, {"s01_case", "s02_other"})
        self.assertEqual(resolved, "s01_case")

    def test_an_unrelated_file_resolves_to_nothing(self):
        self.assertIsNone(scorer.resolve_scenario_id(Path("notes.json"), context.base_packet(), {"s01_case"}))

    def test_claimed_id_names_the_packet_for_the_report(self):
        packet = context.base_packet()
        packet["scenario_id"] = "s12_case"
        self.assertEqual(scorer.claimed_scenario_id(Path("whatever.json"), packet), "s12_case")

    def test_claimed_id_falls_back_to_the_file_stem(self):
        self.assertEqual(
            scorer.claimed_scenario_id(Path("whatever.json"), context.base_packet()), "whatever"
        )

    def test_collection_keys_are_stripped_and_reported(self):
        packet = context.base_packet()
        packet["scenario_id"] = "s01_case"
        stripped, found = scorer.strip_collection_keys(packet)
        self.assertNotIn("scenario_id", stripped)
        self.assertEqual(found, ["scenario_id"])
        self.assertIn("scenario_id", packet, "the caller's packet must not be mutated")

    def test_a_packet_with_no_collection_key_is_returned_unchanged(self):
        packet = context.base_packet()
        stripped, found = scorer.strip_collection_keys(packet)
        self.assertEqual(found, [])
        self.assertIs(stripped, packet)


# --------------------------------------------------------------------------- #
# scoring a directory
# --------------------------------------------------------------------------- #


class TestScoreDirectory(unittest.TestCase):
    def test_a_packet_named_after_a_scenario_is_matched(self):
        scenarios = gold_scenarios()
        target = scenarios[0]
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], copy.deepcopy(target["signals"]))
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["counts"]["missing"], len(scenarios) - 1)
        self.assertNotIn(target["scenario_id"], result["missing"])

    def test_a_packet_with_a_scenario_id_field_is_accepted_and_matched(self):
        """The collection convenience must not make the packet schema-invalid."""
        scenarios = gold_scenarios()
        target = scenarios[0]
        packet = copy.deepcopy(target["signals"])
        packet["scenario_id"] = target["scenario_id"]
        with context.scratch_dir() as tmp:
            write_packet(tmp, "model_output_1", packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["counts"]["invalid"], 0)
        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["counts"]["with_collection_keys"], 1)

    def test_any_other_extra_property_is_still_invalid(self):
        scenarios = gold_scenarios()
        packet = copy.deepcopy(scenarios[0]["signals"])
        packet["notes"] = "this key is not in the schema"
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenarios[0]["scenario_id"], packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["counts"]["invalid"], 1)
        self.assertEqual(result["counts"]["matched"], 0)
        self.assertTrue(any("notes" in error for error in result["invalid"][0]["errors"]))

    def test_a_schema_violation_is_reported_rather_than_raised(self):
        scenarios = gold_scenarios()
        packet = copy.deepcopy(scenarios[0]["signals"])
        packet["relation"]["opposition"] = 3.5
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenarios[0]["scenario_id"], packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["counts"]["invalid"], 1)
        self.assertEqual(result["counts"]["scored"], 0)
        self.assertFalse(result["scored"])
        self.assertTrue(result["invalid"][0]["errors"])

    def test_malformed_json_is_reported_as_unreadable(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            write_text(tmp / "broken.json", "{not json")
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["counts"]["unreadable"], 1)
        self.assertEqual(result["counts"]["files"], 1)
        self.assertIn("JSONDecodeError", result["unreadable"][0]["detail"])

    def test_an_unmatched_packet_is_reported_with_its_claim(self):
        scenarios = gold_scenarios()
        packet = copy.deepcopy(scenarios[0]["signals"])
        packet["run_id"] = "model_session_7"
        with context.scratch_dir() as tmp:
            write_packet(tmp, "not_a_scenario", packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["counts"]["unmatched"], 1)
        self.assertEqual(result["counts"]["matched"], 0)
        self.assertEqual(result["unmatched"][0]["file"], "not_a_scenario.json")

    def test_a_missing_packet_is_reported_as_coverage_loss(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenarios[0]["scenario_id"], copy.deepcopy(scenarios[0]["signals"]))
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["counts"]["missing"], len(scenarios) - 1)
        self.assertNotIn(scenarios[0]["scenario_id"], result["missing"])

    def test_duplicate_packets_are_ignored_deterministically(self):
        scenarios = gold_scenarios()
        target = scenarios[0]
        first = copy.deepcopy(target["signals"])
        second = copy.deepcopy(target["signals"])
        second["relation"]["opposition"] = 0.0
        with context.scratch_dir() as tmp:
            write_packet(tmp, "a_" + target["scenario_id"], first)
            write_packet(tmp, "b_" + target["scenario_id"], second)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["counts"]["matched"], 1)
        self.assertEqual(result["counts"]["duplicate"], 1)

    def test_no_directory_scores_nothing_without_raising(self):
        result = scorer.score(None, context.BASE_CONFIG)
        self.assertFalse(result["scored"])
        self.assertEqual(result["counts"]["files"], 0)
        self.assertIsNone(result["packets_dir"])

    def test_a_directory_that_does_not_exist_scores_nothing(self):
        with context.scratch_dir() as tmp:
            result = scorer.score(tmp / "absent", context.BASE_CONFIG)
        self.assertFalse(result["scored"])
        self.assertFalse(result["packets_dir_exists"])
        self.assertEqual(result["counts"]["files"], 0)

    def test_an_empty_directory_scores_nothing(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertFalse(result["scored"])
        self.assertEqual(result["counts"]["missing"], len(scenarios))

    def test_annotators_are_collected_for_the_report(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            for index, scenario in enumerate(scenarios[:2]):
                packet = copy.deepcopy(scenario["signals"])
                packet["annotator"] = "model-a" if index == 0 else "model-b"
                write_packet(tmp, scenario["scenario_id"], packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["annotators"], ["model-a", "model-b"])

    def test_every_rated_dimension_appears_in_the_result(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenarios[0]["scenario_id"], copy.deepcopy(scenarios[0]["signals"]))
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(set(result["ratings"]), set(scorer.SCALAR_DIMENSIONS))
        self.assertEqual(set(result["evidence_ratings"]), set(scorer.EVIDENCE_DIMENSIONS))

    def test_a_broken_scenario_override_is_reported_and_excluded(self):
        """A gold reference the engine cannot run leaves no decision to compare."""
        scenario = synthetic_scenario(config_overrides={"thresholds": {"alert": 0.9}})
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenario["scenario_id"], copy.deepcopy(scenario["signals"]))
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=[scenario])
        self.assertEqual(result["reference_errors"][0]["scenario_id"], scenario["scenario_id"])
        self.assertEqual(result["decisions"]["all"]["n"], 0)
        self.assertFalse(result["scored"])

    def test_per_scenario_rows_record_both_sides_of_every_decision(self):
        scenario = synthetic_scenario()
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenario["scenario_id"], copy.deepcopy(scenario["signals"]))
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=[scenario])
        entry = result["per_scenario"][0]
        self.assertEqual(entry["scenario_id"], scenario["scenario_id"])
        self.assertEqual(set(entry["reference"]), set(scorer.DECISION_FIELDS))
        self.assertEqual(set(entry["produced"]), set(scorer.DECISION_FIELDS))
        self.assertTrue(entry["checks"]["all"])


# --------------------------------------------------------------------------- #
# decisions
# --------------------------------------------------------------------------- #


class TestDecisionComparison(unittest.TestCase):
    def test_identical_rows_agree_on_every_field(self):
        row = {"level": "alert", "channel": "dissonance", "error": ""}
        checks = scorer.compare_decisions(dict(row), dict(row))
        self.assertTrue(checks["all"])
        for field in scorer.DECISION_FIELDS:
            self.assertTrue(checks[field])

    def test_one_differing_field_breaks_the_roll_up(self):
        reference = {"level": "alert", "channel": "dissonance", "error": ""}
        produced = {"level": "silent", "channel": "dissonance", "error": ""}
        checks = scorer.compare_decisions(reference, produced)
        self.assertFalse(checks["level"])
        self.assertTrue(checks["channel"])
        self.assertFalse(checks["all"])

    def test_an_engine_error_is_never_agreement(self):
        row = {"level": None, "channel": None, "error": "detect_failed: ValueError: x"}
        checks = scorer.compare_decisions(dict(row), dict(row))
        self.assertFalse(checks["all"])
        self.assertFalse(all(checks[field] for field in scorer.DECISION_FIELDS))

    def test_engine_row_runs_the_same_path_as_the_corpus_harness(self):
        from run_scenarios import run_scenario

        scenario = gold_scenarios()[0]
        expected = run_scenario(scenario, context.BASE_CONFIG)
        actual = engine_row(scenario)
        for field in scorer.DECISION_FIELDS:
            self.assertEqual(actual[field], expected[field], field)

    def test_engine_row_honours_a_scenario_config_override(self):
        """A per-scenario override must reach the reference run, not be dropped."""
        scenario = synthetic_scenario()
        row = scorer.engine_row(
            scenario["signals"],
            context.BASE_CONFIG,
            scenario["scenario_id"],
            {"skill": {"interaction": "interactive"}},
        )
        self.assertEqual(row["next_action"], "await_user_decision")

    def test_an_event_that_stops_before_the_evaluator_has_no_strategy(self):
        for scenario in gold_scenarios():
            row = engine_row(scenario)
            if row["error"] or row["next_action"] == "auto_evaluate":
                continue
            self.assertIsNone(row["strategy"])
            return
        self.skipTest("the corpus contains no scenario that stops before the evaluator")

    def test_a_packet_missing_its_stance_still_produces_comparable_decisions(self):
        """The schema makes ``stance`` optional, so a produced packet may omit it.

        The engine must return a row rather than raising, and the comparison must
        still be made — a packet that quietly dropped out of the denominator would
        make the decision agreement look better than it is.
        """
        scenario = synthetic_scenario()
        produced = copy.deepcopy(scenario["signals"])
        produced.pop("stance", None)
        result = scorer.score_pair(scenario, produced, context.BASE_CONFIG)
        self.assertEqual(result["produced_error"], "")
        self.assertEqual(result["reference_error"], "")
        self.assertEqual(set(result["produced"]), set(scorer.DECISION_FIELDS))
        # Without a stance there is no free-choice signal, so the gate must apply
        # where the gold packet's gate did not.
        self.assertFalse(result["checks"]["gate_applied"])
        self.assertFalse(result["checks"]["all"])


# --------------------------------------------------------------------------- #
# round-trip identity: the strongest test in this file
# --------------------------------------------------------------------------- #


class TestRoundTripIdentity(unittest.TestCase):
    """Feeding the gold packets back as "produced" must score perfectly.

    This is what proves the scorer is wired to the engine correctly: a misread field,
    a misaligned evidence item, or a second implementation of the decision path would
    all show up as error on a packet that is, by construction, the gold answer.
    """

    @classmethod
    def setUpClass(cls):
        cls.scenarios = gold_scenarios()
        cls.tmp = context.SCRATCH_ROOT / "perception_round_trip"
        cls.tmp.mkdir(parents=True, exist_ok=True)
        write_gold_packets(cls.tmp, cls.scenarios)
        cls.result = scorer.score(cls.tmp, context.BASE_CONFIG, scenarios=cls.scenarios)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_scenario_is_covered(self):
        self.assertEqual(self.result["counts"]["missing"], 0)
        self.assertEqual(self.result["counts"]["unmatched"], 0)
        self.assertEqual(self.result["counts"]["invalid"], 0)
        self.assertEqual(self.result["counts"]["scored"], len(self.scenarios))

    def test_every_rating_dimension_has_zero_mae(self):
        for group in ("ratings", "evidence_ratings"):
            for name, metrics in self.result[group].items():
                with self.subTest(dimension=name):
                    if metrics["n"] == 0:
                        self.assertIsNone(metrics["mae"], name)
                    else:
                        self.assertEqual(metrics["mae"], 0.0, name)

    def test_every_rating_dimension_is_within_tolerance(self):
        for group in ("ratings", "evidence_ratings"):
            for name, metrics in self.result[group].items():
                if metrics["n"] == 0:
                    continue
                with self.subTest(dimension=name):
                    self.assertEqual(metrics["exact_agreement"], 1.0, name)

    def test_bias_is_zero_everywhere(self):
        for group in ("ratings", "evidence_ratings"):
            for name, metrics in self.result[group].items():
                if metrics["n"] == 0:
                    continue
                with self.subTest(dimension=name):
                    self.assertEqual(metrics["bias"], 0.0, name)

    def test_no_dimension_reports_the_model_as_having_skipped_a_rating(self):
        for group in ("ratings", "evidence_ratings"):
            for name, metrics in self.result[group].items():
                with self.subTest(dimension=name):
                    self.assertEqual(metrics["produced_unrated"], 0, name)

    def test_categorical_agreement_is_total(self):
        metrics = self.result["categorical"]["relation.type"]
        self.assertEqual(metrics["n"], len(self.scenarios))
        self.assertEqual(metrics["agreement"], 1.0)
        self.assertEqual(metrics["confusions"], [])

    def test_every_decision_field_agrees(self):
        for field in scorer.DECISION_FIELDS:
            with self.subTest(field=field):
                metrics = self.result["decisions"][field]
                self.assertEqual(metrics["mismatches"], 0, field)
                self.assertEqual(metrics["agreement"], 1.0, field)

    def test_there_are_no_mismatches_to_attribute(self):
        self.assertEqual(self.result["matches"], [])
        self.assertEqual(self.result["decisions"]["all"]["mismatches"], 0)

    def test_evidence_items_align_by_id_on_a_round_trip(self):
        alignment = self.result["evidence_alignment"]
        self.assertGreater(alignment["paired"], 0)
        self.assertEqual(alignment["paired_by_position"], 0)
        self.assertEqual(alignment["gold_unpaired"], 0)

    def test_strict_mode_passes(self):
        code, _ = run_main(["--packets", str(self.tmp), "--strict"])
        self.assertEqual(code, 0)


class TestPerturbationIsVisible(unittest.TestCase):
    def test_a_packet_that_perceives_no_conflict_loses_decision_agreement(self):
        scenarios = gold_scenarios()
        target = firing_scenario(scenarios)
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], conflict_free_packet(target["signals"]))
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(result["decisions"]["channel"]["agreement"], 0.0)
        self.assertTrue(result["matches"])
        self.assertTrue(
            any("relation.type" in note for entry in result["matches"] for note in entry["attribution"])
        )

    def test_a_rating_deviation_shows_up_in_the_mae_and_the_bias(self):
        scenarios = gold_scenarios()
        target = next(
            scenario
            for scenario in scenarios
            if isinstance((scenario["signals"].get("stance") or {}).get("commitment"), (int, float))
        )
        packet = copy.deepcopy(target["signals"])
        packet["stance"]["commitment"] = max(0.0, packet["stance"]["commitment"] - 0.4)
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        metrics = result["ratings"]["stance.commitment"]
        self.assertEqual(metrics["n"], 1)
        self.assertGreater(metrics["mae"], 0.05)
        self.assertLess(metrics["bias"], 0)

    def test_a_rating_deviation_within_tolerance_counts_as_agreement(self):
        scenarios = gold_scenarios()
        target = next(
            scenario
            for scenario in scenarios
            if isinstance((scenario["signals"].get("stance") or {}).get("commitment"), (int, float))
            and 0.02 <= (scenario["signals"]["stance"]["commitment"] or 0) <= 0.98
        )
        packet = copy.deepcopy(target["signals"])
        packet["stance"]["commitment"] += 0.02
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios, tolerance=0.05)
        metrics = result["ratings"]["stance.commitment"]
        self.assertEqual(metrics["exact_agreement"], 1.0)
        self.assertGreater(metrics["mae"], 0.0)

    def test_an_evidence_item_rated_wrongly_is_attributed_by_dimension_name(self):
        scenarios = gold_scenarios()
        target = next(
            scenario
            for scenario in scenarios
            if (scenario["signals"].get("evidence") or [{}])[0].get("credibility") is not None
        )
        packet = copy.deepcopy(target["signals"])
        packet["evidence"][0]["credibility"] = 0.0 if packet["evidence"][0]["credibility"] > 0.5 else 1.0
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        metrics = result["evidence_ratings"]["evidence.credibility"]
        self.assertEqual(metrics["n"], 1)
        self.assertGreater(metrics["mae"], 0.4)


# --------------------------------------------------------------------------- #
# determinism and the report
# --------------------------------------------------------------------------- #


class TestDeterminism(unittest.TestCase):
    def test_two_runs_over_the_same_packets_are_identical(self):
        scenarios = gold_scenarios()
        target = scenarios[0]
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], copy.deepcopy(target["signals"]))
            first = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
            second = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
        self.assertEqual(
            json.dumps(first, sort_keys=True, ensure_ascii=False),
            json.dumps(second, sort_keys=True, ensure_ascii=False),
        )

    def test_two_reports_over_the_same_packets_are_byte_identical(self):
        scenarios = gold_scenarios()
        target = scenarios[0]
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], copy.deepcopy(target["signals"]))
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
            first = scorer.write_report(result, path=tmp / "one.md")
            second = scorer.write_report(result, path=tmp / "two.md")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_the_not_yet_run_report_is_byte_identical_across_runs(self):
        with context.scratch_dir() as tmp:
            result = scorer.score(None, context.BASE_CONFIG, scenarios=gold_scenarios())
            first = scorer.write_report(result, path=tmp / "one.md")
            second = scorer.write_report(result, path=tmp / "two.md")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_a_report_over_the_whole_corpus_is_byte_identical_across_runs(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            write_gold_packets(tmp, scenarios)
            first = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
            second = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
            one = scorer.write_report(first, path=tmp / "one.md").read_bytes()
            two = scorer.write_report(second, path=tmp / "two.md").read_bytes()
        self.assertEqual(one, two)

    def test_the_report_carries_no_timestamp_by_default(self):
        with context.scratch_dir() as tmp:
            result = scorer.score(None, context.BASE_CONFIG, scenarios=gold_scenarios())
            text = scorer.write_report(result, path=tmp / "r.md").read_text(encoding="utf-8")
        self.assertNotIn("generated at", text)

    def test_a_stamp_is_clearly_marked_as_non_deterministic(self):
        with context.scratch_dir() as tmp:
            result = scorer.score(None, context.BASE_CONFIG, scenarios=gold_scenarios())
            text = scorer.write_report(result, path=tmp / "r.md", stamp="2026-01-01T00:00:00Z").read_text(
                encoding="utf-8"
            )
        self.assertIn("2026-01-01T00:00:00Z", text)
        self.assertIn("non-deterministic", text)


class TestReportContent(unittest.TestCase):
    def not_yet_run_text(self):
        with context.scratch_dir() as tmp:
            result = scorer.score(None, context.BASE_CONFIG, scenarios=gold_scenarios())
            return scorer.write_report(result, path=tmp / "r.md").read_text(encoding="utf-8")

    def scored_text(self, packet_for):
        scenarios = gold_scenarios()
        target = firing_scenario(scenarios)
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], packet_for(target))
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
            return scorer.write_report(result, path=tmp / "r.md").read_text(encoding="utf-8")

    def test_the_not_yet_run_report_says_so(self):
        text = self.not_yet_run_text()
        self.assertIn("not yet run", text)
        self.assertIn("no perception number", text)

    def test_the_not_yet_run_report_explains_the_protocol(self):
        text = self.not_yet_run_text()
        self.assertIn("Packet collection protocol", text)
        self.assertIn("--packets", text)
        self.assertIn("codebook", text)
        self.assertIn("detect.md", text)

    def test_the_not_yet_run_report_says_what_will_be_reported(self):
        text = self.not_yet_run_text()
        self.assertIn("What will be reported", text)
        self.assertIn("MAE", text)
        self.assertIn("Decision agreement", text)

    def test_the_not_yet_run_report_emits_no_empty_result_tables(self):
        text = self.not_yet_run_text()
        self.assertNotIn("## Rating agreement per dimension", text)
        self.assertNotIn("## Downstream decision agreement", text)

    def test_the_not_yet_run_report_keeps_the_caveat_block(self):
        self.assertIn("What this number cannot show", self.not_yet_run_text())

    def test_the_not_yet_run_report_lists_the_rated_dimensions(self):
        text = self.not_yet_run_text()
        for name in scorer.ALL_DIMENSIONS:
            with self.subTest(dimension=name):
                self.assertIn(f"`{name}`", text)

    def test_the_not_yet_run_report_states_why_it_may_be_empty(self):
        self.assertIn("must not fail the build", self.not_yet_run_text())

    def test_a_scored_report_contains_every_table(self):
        text = self.scored_text(lambda target: copy.deepcopy(target["signals"]))
        for heading in (
            "## Rating agreement per dimension",
            "### Per evidence item",
            "### Evidence alignment",
            "## Categorical agreement",
            "## Downstream decision agreement",
            "## Attribution",
            "## Coverage",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, text)

    def test_a_scored_report_keeps_the_caveat_block(self):
        self.assertIn(
            "What this number cannot show",
            self.scored_text(lambda target: copy.deepcopy(target["signals"])),
        )

    def test_a_mismatch_is_tabulated_with_its_attribution(self):
        text = self.scored_text(lambda target: conflict_free_packet(target["signals"]))
        self.assertIn("relation.type", text)

    def test_an_invalid_packet_is_listed_in_the_report(self):
        def break_it(target):
            packet = copy.deepcopy(target["signals"])
            packet["relation"]["opposition"] = 9.0
            return packet

        text = self.scored_text(break_it)
        self.assertIn("Invalid packets", text)
        self.assertIn("not yet run", text)

    def test_an_unmatched_packet_is_listed_in_the_report(self):
        scenarios = gold_scenarios()
        packet = copy.deepcopy(scenarios[0]["signals"])
        packet["run_id"] = "model_session_1"
        with context.scratch_dir() as tmp:
            write_packet(tmp, "stray_packet", packet)
            result = scorer.score(tmp, context.BASE_CONFIG, scenarios=scenarios)
            text = scorer.write_report(result, path=tmp / "r.md").read_text(encoding="utf-8")
        self.assertIn("stray_packet.json", text)

    def test_the_report_is_lf_and_bom_free(self):
        with context.scratch_dir() as tmp:
            result = scorer.score(None, context.BASE_CONFIG, scenarios=gold_scenarios())
            data = scorer.write_report(result, path=tmp / "r.md").read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertNotIn(b"\xef\xbb\xbf", data)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class TestCli(unittest.TestCase):
    def test_running_without_packets_exits_zero(self):
        code, output = run_main([])
        self.assertEqual(code, 0)
        self.assertIn("nothing to score", output)

    def test_strict_without_packets_still_exits_zero(self):
        """CI runs on a repository with no packets; that must not fail the build."""
        code, _ = run_main(["--strict"])
        self.assertEqual(code, 0)

    def test_strict_exits_non_zero_on_a_decision_mismatch(self):
        scenarios = gold_scenarios()
        target = firing_scenario(scenarios)
        with context.scratch_dir() as tmp:
            write_packet(tmp, target["scenario_id"], conflict_free_packet(target["signals"]))
            code, output = run_main(["--packets", str(tmp), "--strict"])
            lenient, _ = run_main(["--packets", str(tmp)])
        self.assertEqual(code, 1)
        self.assertEqual(lenient, 0)
        self.assertIn("mismatched decisions", output)

    def test_strict_exits_zero_when_every_decision_agrees(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            write_gold_packets(tmp, scenarios)
            code, _ = run_main(["--packets", str(tmp), "--strict"])
        self.assertEqual(code, 0)

    def test_strict_exits_zero_when_a_packet_is_invalid(self):
        """An invalid packet is a reported finding, not a decision mismatch."""
        scenarios = gold_scenarios()
        packet = copy.deepcopy(scenarios[0]["signals"])
        packet["relation"]["opposition"] = 9.0
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenarios[0]["scenario_id"], packet)
            code, _ = run_main(["--packets", str(tmp), "--strict"])
        self.assertEqual(code, 0)

    def test_json_mode_emits_parseable_output(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenarios[0]["scenario_id"], copy.deepcopy(scenarios[0]["signals"]))
            code, output = run_main(["--packets", str(tmp), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["counts"]["scored"], 1)

    def test_json_output_contains_no_non_finite_numbers(self):
        scenarios = gold_scenarios()
        with context.scratch_dir() as tmp:
            write_packet(tmp, scenarios[0]["scenario_id"], copy.deepcopy(scenarios[0]["signals"]))
            _, output = run_main(["--packets", str(tmp), "--json"])
        self.assertNotIn("NaN", output)
        self.assertNotIn("Infinity", output)

    def test_a_negative_tolerance_is_rejected(self):
        # argparse prints its usage to stderr on error; keep it out of the run log.
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                run_main(["--tolerance", "-0.1"])


if __name__ == "__main__":
    unittest.main()
