"""Tests for the CDS Tension Index, the gate, and the two channels."""

from __future__ import annotations

import math
import unittest

import context

from cds_config import load_schema
from cds_index import build_detection, build_event_id, build_terms, volition_self_value
from jsonschema_lite import validate


class TestFixtureArithmetic(unittest.TestCase):
    """Pin the fixture itself, so a drift in either the fixture or the formula is loud."""

    def test_baseline_index_is_alert(self):
        detection = build_detection(context.base_packet(), context.BASE_CONFIG)
        self.assertAlmostEqual(detection["tension_result"]["tension"], 0.686, places=9)
        self.assertEqual(detection["tension_result"]["level"], "alert")

    def test_baseline_evidence_score(self):
        from cds_evaluator import build_evaluation

        detection = build_detection(context.base_packet(), context.BASE_CONFIG)
        evaluation = build_evaluation(detection, context.base_packet(), context.BASE_CONFIG)
        # 0.25*0.80 + 0.25*0.55 + 0.15*0.70 + 0.15*0.40 + 0.20*0.50 = 0.6025
        self.assertAlmostEqual(evaluation["evaluation_result"]["evidence_score"], 0.6025, places=9)


class TestTerms(unittest.TestCase):
    def test_contributions_sum_to_raw_index(self):
        terms = build_terms(context.base_packet(), context.BASE_CONFIG)
        self.assertAlmostEqual(sum(term["contribution"] for term in terms.values()), 0.686, places=9)

    def test_every_term_names_its_decomposition(self):
        terms = build_terms(context.base_packet(), context.BASE_CONFIG)
        for name in ("opposition", "commitment", "volition_self", "specificity", "novelty"):
            self.assertIn(name, terms)
            for key in ("raw", "weight", "contribution"):
                self.assertIn(key, terms[name])
            self.assertAlmostEqual(terms[name]["raw"] * terms[name]["weight"], terms[name]["contribution"], places=12)

    def test_weights_match_the_config(self):
        terms = build_terms(context.base_packet(), context.BASE_CONFIG)
        for name, term in terms.items():
            self.assertEqual(term["weight"], context.BASE_CONFIG["index"]["weights"][name])

    def test_novelty_is_the_max_over_carrying_evidence(self):
        packet = context.base_packet()
        packet["evidence"] = [
            {**packet["evidence"][0], "id": "ev_001", "novelty": 0.20},
            {**packet["evidence"][0], "id": "ev_002", "novelty": 0.90},
        ]
        terms = build_terms(packet, context.BASE_CONFIG)
        self.assertAlmostEqual(terms["novelty"]["raw"], 0.90, places=9)

    def test_user_pressure_is_not_a_term(self):
        """The sycophancy channel v0.1 built into the index must stay closed."""
        quiet = context.base_packet(user_pressure=0.0)
        loud = context.base_packet(user_pressure=1.0)
        low = build_detection(quiet, context.BASE_CONFIG)["tension_result"]["tension"]
        high = build_detection(loud, context.BASE_CONFIG)["tension_result"]["tension"]
        self.assertAlmostEqual(low, high, places=12)
        self.assertNotIn("user_pressure", build_terms(quiet, context.BASE_CONFIG))
        # ... but it is still logged, because it moderates the strategy choice.
        self.assertEqual(build_detection(loud, context.BASE_CONFIG)["conflict_event"]["user_pressure"], 1.0)

    def test_repeated_objections_do_not_raise_tension(self):
        """v0.1 added 0.10 * repetition; restarting a stale complaint must not escalate."""
        stale = context.base_packet()
        stale["evidence"][0]["novelty"] = 0.0
        fresh = context.base_packet()
        fresh["evidence"][0]["novelty"] = 1.0
        stale_tension = build_detection(stale, context.BASE_CONFIG)["tension_result"]["tension"]
        fresh_tension = build_detection(fresh, context.BASE_CONFIG)["tension_result"]["tension"]
        self.assertLess(stale_tension, fresh_tension)


class TestVolitionGate(unittest.TestCase):
    def test_volition_self_is_the_product(self):
        stance = {"volition": 0.8, "self_relevance": 0.5}
        volition, self_relevance, value = volition_self_value(stance)
        self.assertAlmostEqual(volition, 0.8, places=12)
        self.assertAlmostEqual(self_relevance, 0.5, places=12)
        self.assertAlmostEqual(value, 0.4, places=12)
        self.assertAlmostEqual(value, volition * self_relevance, places=12)

    def test_missing_stance_rates_zero(self):
        self.assertEqual(volition_self_value(None), (0.0, 0.0, 0.0))

    def test_assigned_stance_is_capped_and_silent(self):
        packet = context.base_packet()
        # volition * self_relevance = 0.10, well below the 0.30 floor.
        packet["stance"]["volition"] = 0.20
        packet["stance"]["self_relevance"] = 0.50
        detection = build_detection(packet, context.BASE_CONFIG)

        self.assertTrue(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(detection["conflict_event"]["gate"]["rule"], "volition_floor")
        self.assertGreaterEqual(detection["conflict_event"]["raw_index"], 0.55)
        self.assertEqual(detection["tension_result"]["tension"], 0.40)
        self.assertEqual(detection["tension_result"]["level"], "silent")
        self.assertEqual(detection["tension_result"]["channel"], "none")

    def test_gate_boundary_is_where_the_config_says(self):
        floor = context.BASE_CONFIG["index"]["gates"]["volition_floor"]
        for volition, expected_applied in ((floor - 0.01, True), (floor, False), (floor + 0.01, False)):
            with self.subTest(volition=volition):
                packet = context.base_packet()
                packet["stance"]["volition"] = volition
                packet["stance"]["self_relevance"] = 1.0
                detection = build_detection(packet, context.BASE_CONFIG)
                self.assertEqual(detection["conflict_event"]["gate"]["applied"], expected_applied)

    def test_cap_can_never_reach_an_alert_threshold(self):
        """The config invariant that keeps the gate meaningful must actually be enforced."""
        from cds_config import ConfigError, check_semantics

        broken = context.config_with()
        broken["index"]["gates"]["non_dissonant_cap"] = 0.60
        with self.assertRaises(ConfigError):
            check_semantics(broken)

    def test_per_type_threshold_cannot_undercut_the_cap(self):
        from cds_config import ConfigError, check_semantics

        broken = context.config_with()
        broken["thresholds_by_type"]["evidence_vs_stance"] = 0.30
        with self.assertRaises(ConfigError):
            check_semantics(broken)


class TestLevelsAndChannels(unittest.TestCase):
    def test_levels_track_the_thresholds(self):
        config = context.BASE_CONFIG
        high = config["thresholds"]["high"]
        alert = config["thresholds"]["alert"]
        cases = [("silent", alert - 0.01), ("alert", alert), ("high", high)]
        for expected, target in cases:
            with self.subTest(target=target):
                packet = context.base_packet()
                # Solve for the opposition that puts the index on the target value.
                other = 0.25 * 0.60 + 0.20 * 0.72 + 0.12 * 0.60 + 0.08 * 0.50
                packet["relation"]["opposition"] = (target - other) / 0.35
                detection = build_detection(packet, config)
                self.assertAlmostEqual(detection["tension_result"]["tension"], target, places=9)
                self.assertEqual(detection["tension_result"]["level"], expected)

    def test_per_type_override_wins(self):
        config = context.config_with()
        config["thresholds_by_type"]["evidence_vs_stance"] = 0.70
        detection = build_detection(context.base_packet(), config)
        # tension 0.686 now sits below the per-type alert of 0.70
        self.assertEqual(detection["tension_result"]["level"], "silent")
        self.assertEqual(detection["tension_result"]["threshold_source"], "thresholds_by_type:evidence_vs_stance")

    def test_the_global_alert_is_live_for_types_without_an_override(self):
        """Regression guard: with every type overridden, thresholds.alert did nothing
        and the sensitivity sweep reported a false zero."""
        config = context.BASE_CONFIG
        self.assertNotIn("evidence_vs_stance", config.get("thresholds_by_type") or {})
        lowered = context.config_with(thresholds={"alert": 0.40})
        detection = build_detection(context.base_packet(), lowered)
        self.assertEqual(detection["tension_result"]["threshold_source"], "global")
        # 0.686 clears both 0.55 and 0.40, but the reported threshold must move.
        self.assertEqual(detection["tension_result"]["threshold_alert"], 0.40)

    def test_indeterminacy_is_ungated_and_labelled_separately(self):
        packet = {
            "run_id": "test_run",
            "turn_id": 1,
            "annotator": "test",
            "relation": {
                "type": "evidence_vs_evidence",
                "opposition": 1.0,
                "specificity": 0.9,
                "rationale": "two studies disagree",
            },
            "evidence": [
                {
                    "id": "ev_001",
                    "claim": "X holds",
                    "quote": "X holds in all sites.",
                    "carries_conflict": True,
                    "novelty": 1.0,
                    "relevance": 1.0,
                    "credibility": 0.9,
                    "recency": 1.0,
                    "independence": 1.0,
                    "consistency": 0.0,
                },
                {
                    "id": "ev_002",
                    "claim": "X does not hold",
                    "quote": "X fails in all sites.",
                    "carries_conflict": True,
                    "novelty": 1.0,
                    "relevance": 1.0,
                    "credibility": 0.9,
                    "recency": 1.0,
                    "independence": 1.0,
                    "consistency": 0.0,
                },
            ],
            "user_pressure": 0.0,
            "evidence_conflict_unresolved": 0.90,
            "consistency_gate": {"internal_contradiction": 0.0},
        }
        detection = build_detection(packet, context.BASE_CONFIG)
        result = detection["tension_result"]

        # No stance means the gate caps the index, so the dissonance channel stays shut.
        self.assertTrue(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(result["channel_levels"]["dissonance"], "silent")
        # The indeterminacy channel is ungated and does fire.
        self.assertEqual(result["channel"], "indeterminacy")
        self.assertEqual(result["level"], "high")
        self.assertAlmostEqual(result["indeterminacy"], 0.90, places=9)

    def test_none_relation_is_silent(self):
        packet = context.base_packet()
        packet["relation"] = {"type": "none", "opposition": 0.0, "specificity": 0.0}
        packet.pop("stance")
        packet["evidence"] = []
        detection = build_detection(packet, context.BASE_CONFIG)
        self.assertEqual(detection["tension_result"]["level"], "silent")
        self.assertEqual(detection["tension_result"]["channel"], "none")
        self.assertEqual(detection["tension_result"]["next_action"], "log_only")


class TestConsistencyGate(unittest.TestCase):
    def test_self_contradiction_never_moves_the_index(self):
        clean = context.base_packet()
        dirty = context.base_packet()
        dirty["consistency_gate"]["internal_contradiction"] = 0.95
        clean_detection = build_detection(clean, context.BASE_CONFIG)
        dirty_detection = build_detection(dirty, context.BASE_CONFIG)
        self.assertAlmostEqual(
            clean_detection["tension_result"]["tension"], dirty_detection["tension_result"]["tension"], places=12
        )
        self.assertFalse(clean_detection["consistency_gate_result"]["flagged"])
        self.assertTrue(dirty_detection["consistency_gate_result"]["flagged"])
        self.assertEqual(dirty_detection["consistency_gate_result"]["route"], "consistency_report")


class TestDeterminism(unittest.TestCase):
    def test_same_packet_yields_the_same_detection(self):
        first = build_detection(context.base_packet(), context.BASE_CONFIG)
        second = build_detection(context.base_packet(), context.BASE_CONFIG)
        self.assertEqual(first, second)

    def test_event_id_is_stable_and_content_addressed(self):
        packet = context.base_packet()
        self.assertEqual(build_event_id(packet), build_event_id(context.base_packet()))
        self.assertTrue(build_event_id(packet).startswith("cds_evt_"))

        changed = context.base_packet()
        changed["turn_id"] = 99
        self.assertNotEqual(build_event_id(packet), build_event_id(changed))

    def test_timestamp_does_not_change_the_event_id(self):
        stamped = context.base_packet(detected_at="2026-01-01T00:00:00Z")
        self.assertEqual(build_event_id(context.base_packet()), build_event_id(stamped))


class TestSummationIsInterpreterIndependent(unittest.TestCase):
    """The index must not depend on the interpreter's summation algorithm.

    CPython 3.12 replaced builtin ``sum``'s naive loop with Neumaier compensated
    summation, so the same term vector can land one ulp either side of a level
    boundary on 3.9 and 3.12. Here the term vector totals exactly ``0.75`` in
    decimal, which is also ``thresholds.high``, so a naive accumulation decides the
    level by rounding error rather than by arithmetic: on 3.9 it returns
    ``0.7499999999999999`` and the level silently drops to ``alert``. The index uses
    ``math.fsum``, which is exactly rounded and identical on both versions.
    """

    def _ratings_from_s43(self) -> tuple[dict, dict]:
        """s43's ratings with its novelty weight perturbed as the sweep perturbs it.

        Weights are renormalised exactly as ``sensitivity.evaluator_weight_sweep``
        does for its ``novelty +`` row, which is the row this defect was found on.
        """
        config = context.config_with()
        weights = dict(config["index"]["weights"])
        weights["novelty"] = weights["novelty"] + 0.05
        total = math.fsum(weights.values())
        config["index"]["weights"] = {name: value / total for name, value in weights.items()}

        packet = context.base_packet(
            relation={"opposition": 0.85, "specificity": 0.7},
            stance={"commitment": 0.70, "volition": 0.85, "self_relevance": 0.90},
            evidence=[{**context.base_packet()["evidence"][0], "novelty": 0.60}],
        )
        return packet, config

    def test_raw_index_is_exactly_rounded(self):
        packet, config = self._ratings_from_s43()
        terms = build_terms(packet, config)
        # 0.35*0.85 + 0.25*0.70 + 0.20*(0.85*0.90) + 0.12*0.70 + 0.1238...*0.60
        self.assertEqual(math.fsum(term["contribution"] for term in terms.values()), 0.75)
        detection = build_detection(packet, config)
        self.assertEqual(detection["tension_result"]["tension"], 0.75)

    def test_a_term_vector_exactly_on_the_high_threshold_reads_high(self):
        packet, config = self._ratings_from_s43()
        detection = build_detection(packet, config)
        self.assertEqual(detection["tension_result"]["tension"], config["thresholds"]["high"])
        self.assertEqual(detection["tension_result"]["level"], "high")


class TestDetectionSchema(unittest.TestCase):
    def test_output_satisfies_the_published_schema(self):
        detection = build_detection(context.base_packet(), context.BASE_CONFIG)
        detection["state"] = {"from": "MONITORING", "to": "EVALUATING", "open_events": 1}
        errors = validate(load_schema("detection"), detection)
        self.assertEqual(errors, [], f"detection schema violations: {errors}")

    def test_none_relation_output_satisfies_the_schema(self):
        packet = context.base_packet()
        packet["relation"] = {"type": "none", "opposition": 0.0, "specificity": 0.0}
        packet.pop("stance")
        packet["evidence"] = []
        detection = build_detection(packet, context.BASE_CONFIG)
        detection["state"] = {"from": "MONITORING", "to": "MONITORING", "open_events": 0}
        errors = validate(load_schema("detection"), detection)
        self.assertEqual(errors, [], f"detection schema violations: {errors}")


if __name__ == "__main__":
    unittest.main()
