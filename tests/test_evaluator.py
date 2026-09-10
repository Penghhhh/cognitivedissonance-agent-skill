"""Tests for the evaluator: scoring, renormalisation, routing and refusal."""

from __future__ import annotations

import copy
import unittest

import context

from cds_config import load_schema
from cds_evaluator import (
    ADJUSTMENT_DIMENSIONS,
    BRANCH_OF_STRATEGY,
    EVIDENCE_DIMENSIONS,
    StageError,
    _route,
    build_evaluation,
)
from cds_index import build_detection
from jsonschema_lite import validate


def evaluate(packet=None, config=None):
    packet = packet or context.base_packet()
    config = config or context.BASE_CONFIG
    detection = build_detection(packet, config)
    return build_evaluation(detection, packet, config)


class TestEvidenceScore(unittest.TestCase):
    def test_score_is_the_documented_weighted_mean(self):
        result = evaluate()["evaluation_result"]
        # 0.25*0.80 + 0.25*0.55 + 0.15*0.70 + 0.15*0.40 + 0.20*0.50
        self.assertAlmostEqual(result["evidence_score"], 0.6025, places=9)

    def test_detail_contributions_sum_to_the_score(self):
        result = evaluate()["evaluation_result"]
        self.assertAlmostEqual(
            sum(entry["contribution"] for entry in result["evidence_detail"].values()),
            result["evidence_score"],
            places=12,
        )

    def test_non_carrying_evidence_is_excluded(self):
        packet = context.base_packet()
        packet["evidence"].append(
            {
                "id": "ev_decoy",
                "claim": "context only",
                "carries_conflict": False,
                "novelty": 1.0,
                "relevance": 1.0,
                "credibility": 1.0,
                "recency": 1.0,
                "independence": 1.0,
                "consistency": 1.0,
                "quote": "decoy",
            }
        )
        result = evaluate(packet)["evaluation_result"]
        self.assertEqual(result["member_evidence_ids"], ["ev_001"])
        self.assertAlmostEqual(result["evidence_score"], 0.6025, places=9)

    def test_missing_dimensions_are_dropped_and_weights_renormalised(self):
        packet = context.base_packet()
        del packet["evidence"][0]["independence"]
        result = evaluate(packet)["evaluation_result"]

        self.assertEqual(result["dropped_dimensions"], ["independence"])
        self.assertNotIn("independence", result["evidence_detail"])
        # Weights are renormalised over the four remaining dimensions, not zeroed.
        self.assertAlmostEqual(sum(entry["weight"] for entry in result["evidence_detail"].values()), 1.0, places=12)
        expected = (0.25 * 0.80 + 0.25 * 0.55 + 0.15 * 0.70 + 0.20 * 0.50) / 0.85
        self.assertAlmostEqual(result["evidence_score"], expected, places=9)

    def test_dimensions_are_averaged_over_items(self):
        packet = context.base_packet()
        second = copy.deepcopy(packet["evidence"][0])
        second["id"] = "ev_002"
        second["credibility"] = 0.05
        packet["evidence"].append(second)
        result = evaluate(packet)["evaluation_result"]
        self.assertAlmostEqual(result["evidence_detail"]["credibility"]["mean_raw"], 0.30, places=9)

    def test_all_five_dimensions_are_rated_when_present(self):
        result = evaluate()["evaluation_result"]
        self.assertEqual(set(result["evidence_detail"]), set(EVIDENCE_DIMENSIONS))
        self.assertEqual(result["dropped_dimensions"], [])


class TestCostAndScores(unittest.TestCase):
    def test_adjustment_cost_is_the_documented_composite(self):
        result = evaluate()["evaluation_result"]
        # 0.45*0.60 + 0.35*0.55 + 0.20*(0.80*0.90) = 0.45*0.60 + 0.35*0.55 + 0.20*0.72
        self.assertAlmostEqual(result["adjustment_cost"], 0.6065, places=9)
        self.assertAlmostEqual(
            sum(entry["contribution"] for entry in result["adjustment_cost_detail"].values()),
            result["adjustment_cost"],
            places=12,
        )
        self.assertEqual(set(result["adjustment_cost_detail"]), set(ADJUSTMENT_DIMENSIONS))

    def test_maintain_and_recalibrate_use_disjoint_inputs(self):
        result = evaluate()["evaluation_result"]
        evidence_score = result["evidence_score"]
        commitment = result["stance_commitment"]
        cost = result["adjustment_cost"]
        self.assertAlmostEqual(
            result["maintain_score"], (1 - evidence_score) * (0.5 + 0.5 * commitment) * (0.5 + 0.5 * cost), places=9
        )
        self.assertAlmostEqual(result["recalibrate_score"], evidence_score * (1 - 0.5 * cost), places=9)

    def test_recalibrate_rises_with_evidence_quality(self):
        weak = context.base_packet()
        weak["evidence"][0].update({"credibility": 0.05, "relevance": 0.20, "consistency": 0.05, "recency": 0.10})
        strong = context.base_packet()
        strong["evidence"][0].update({"credibility": 0.95, "relevance": 0.95, "consistency": 0.95, "recency": 0.95})
        self.assertLess(
            evaluate(weak)["evaluation_result"]["recalibrate_score"],
            evaluate(strong)["evaluation_result"]["recalibrate_score"],
        )
        self.assertGreater(
            evaluate(weak)["evaluation_result"]["maintain_score"],
            evaluate(strong)["evaluation_result"]["maintain_score"],
        )


class TestRouting(unittest.TestCase):
    """Route directly on synthetic facts so every rule is covered without a packet."""

    RULES = context.BASE_CONFIG["evaluator"]["strategy_rules"]

    @staticmethod
    def facts(**overrides):
        base = {
            "e_score": 0.5,
            "commitment": 0.5,
            "public_commitment": 0.5,
            "volition_self": 0.7,
            "adjustment_cost": 0.5,
            "maintain_score": 0.3,
            "recalibrate_score": 0.4,
            "user_pressure": 0.0,
            "evidence_conflict_unresolved": 0.0,
            "tension": 0.6,
            "opposition": 0.7,
            "resolved_profile": "adaptive",
        }
        base.update(overrides)
        return base

    def test_unresolved_conflict_wins_first_in_the_adaptive_arm(self):
        strategy, rule = _route(
            self.facts(evidence_conflict_unresolved=0.9, e_score=0.9, resolved_profile="adaptive"),
            self.RULES,
        )
        self.assertEqual(strategy, "suspend_and_verify")
        self.assertEqual(rule, "R01_unresolved_conflict")

    def test_unresolved_conflict_stays_on_the_reduction_branch(self):
        """R01 is guarded by profile so the reduction arm cannot emit an adaptive strategy.

        Before v0.3.0 R01 was unguarded, and 9 of the 52 routable corpus cases
        realised suspend_and_verify (an adaptive strategy) while nominally in the
        dissonance_reduction arm. That is the contamination the profile guard
        removes.
        """
        strategy, _ = _route(
            self.facts(evidence_conflict_unresolved=0.9, e_score=0.9, resolved_profile="dissonance_reduction"),
            self.RULES,
        )
        self.assertNotEqual(strategy, "suspend_and_verify")
        self.assertEqual(BRANCH_OF_STRATEGY[strategy], "dissonance_reduction")

    def test_pressure_with_weak_evidence_holds_under_pressure(self):
        strategy, rule = _route(self.facts(user_pressure=0.9, e_score=0.20), self.RULES)
        self.assertEqual(strategy, "hold_under_pressure")
        self.assertEqual(rule, "R02_pressure_low_evidence")

    def test_pressure_with_strong_evidence_does_not_trigger_the_pressure_rule(self):
        strategy, _ = _route(self.facts(user_pressure=0.9, e_score=0.90), self.RULES)
        self.assertEqual(strategy, "recalibrate")

    def test_adaptive_bands(self):
        self.assertEqual(_route(self.facts(e_score=0.20, commitment=0.9), self.RULES)[0], "maintain_with_caveat")
        self.assertEqual(_route(self.facts(e_score=0.50), self.RULES)[0], "qualify")
        self.assertEqual(_route(self.facts(e_score=0.90), self.RULES)[0], "recalibrate")

    def test_adaptive_weak_evidence_with_low_commitment_falls_through_to_qualify(self):
        strategy, rule = _route(self.facts(e_score=0.20, commitment=0.30), self.RULES)
        self.assertEqual(strategy, "qualify")
        self.assertEqual(rule, "R04_adaptive_partial_evidence")

    def test_reduction_bands(self):
        reduction = {"resolved_profile": "dissonance_reduction"}
        self.assertEqual(_route(self.facts(e_score=0.20, **reduction), self.RULES)[0], "trivialize")
        self.assertEqual(
            _route(self.facts(e_score=0.50, commitment=0.9, **reduction), self.RULES)[0], "trivialize"
        )
        self.assertEqual(
            _route(self.facts(e_score=0.50, commitment=0.3, **reduction), self.RULES)[0], "reduce_commitment"
        )
        self.assertEqual(
            _route(self.facts(e_score=0.80, commitment=0.90, **reduction), self.RULES)[0], "deny_evidence"
        )
        self.assertEqual(
            _route(self.facts(e_score=0.80, commitment=0.60, **reduction), self.RULES)[0], "rationalize"
        )
        self.assertEqual(
            _route(self.facts(e_score=0.80, commitment=0.20, **reduction), self.RULES)[0], "reduce_commitment"
        )

    def test_the_reduction_arm_never_emits_an_adaptive_strategy(self):
        """The arm is only interpretable if its repertoire is the one it names.

        This is the property that makes 'branch discriminability' a testable
        claim rather than a restatement of the treatment.
        """
        import itertools

        grid = {
            "e_score": [0.10, 0.34, 0.50, 0.64, 0.80, 0.95],
            "commitment": [0.10, 0.55, 0.60, 0.75, 0.95],
            "user_pressure": [0.0, 0.9],
            "evidence_conflict_unresolved": [0.0, 0.7],
        }
        keys = list(grid)
        seen: set[str] = set()
        for combination in itertools.product(*(grid[key] for key in keys)):
            facts = self.facts(resolved_profile="dissonance_reduction", **dict(zip(keys, combination)))
            strategy, _ = _route(facts, self.RULES)
            seen.add(strategy)
            self.assertEqual(
                BRANCH_OF_STRATEGY[strategy],
                "dissonance_reduction",
                f"reduction arm emitted {strategy!r} for {dict(zip(keys, combination))}",
            )
        self.assertEqual(
            seen,
            {"trivialize", "reduce_commitment", "deny_evidence", "rationalize", "hold_under_pressure"},
            "the reduction arm should be able to reach all five reduction strategies",
        )

    def test_the_adaptive_arm_only_leaks_through_the_pressure_rule(self):
        """R02 is deliberately unguarded; it must be the only leak.

        Pressure is a situational fact rather than a property of the profile, so
        an adaptive run may legitimately answer it with hold_under_pressure. Every
        other reduction strategy must be unreachable from the adaptive arm.
        """
        import itertools

        grid = {
            "e_score": [0.10, 0.34, 0.50, 0.64, 0.80, 0.95],
            "commitment": [0.10, 0.55, 0.60, 0.75, 0.95],
            "user_pressure": [0.0, 0.9],
            "evidence_conflict_unresolved": [0.0, 0.7],
        }
        keys = list(grid)
        leaked: set[str] = set()
        for combination in itertools.product(*(grid[key] for key in keys)):
            facts = self.facts(resolved_profile="adaptive", **dict(zip(keys, combination)))
            strategy, rule = _route(facts, self.RULES)
            if BRANCH_OF_STRATEGY[strategy] == "dissonance_reduction":
                leaked.add(strategy)
                self.assertEqual(rule, "R02_pressure_low_evidence", f"{strategy} leaked via {rule}")
        self.assertEqual(leaked, {"hold_under_pressure"}, "the adaptive arm leaked more than the pressure rule")

    def test_every_configured_rule_is_reachable(self):
        """A rule that no input can fire is a spec bug, not a spare part."""
        fired: set[str] = set()
        grid = {
            "e_score": [0.10, 0.50, 0.90],
            "commitment": [0.20, 0.60, 0.90],
            "user_pressure": [0.0, 0.9],
            "evidence_conflict_unresolved": [0.0, 0.9],
            "resolved_profile": ["adaptive", "dissonance_reduction"],
        }
        import itertools

        keys = list(grid)
        for combination in itertools.product(*(grid[key] for key in keys)):
            facts = self.facts(**dict(zip(keys, combination)))
            fired.add(_route(facts, self.RULES)[1])
        configured = {rule["id"] for rule in self.RULES["rules"]}
        self.assertEqual(configured - fired, set(), "unreachable strategy rules")

    def test_tension_does_not_enter_routing(self):
        """Routing reads the evaluation, never the raw index."""
        low = _route(self.facts(tension=0.0), self.RULES)
        high = _route(self.facts(tension=1.0), self.RULES)
        self.assertEqual(low, high)

    def test_unknown_condition_raises(self):
        with self.assertRaises(StageError):
            _route(self.facts(), {"rules": [{"id": "bad", "if": {"nonsense": 1}, "strategy": "qualify"}], "default": "qualify"})


class TestProfiles(unittest.TestCase):
    def test_mixed_resolves_per_event_and_reports_tendency(self):
        config = context.config_with(skill={"profile": "mixed"})

        low = context.base_packet()
        low["stance"].update({"commitment": 0.05, "public_commitment": 0.05})
        low["user_pressure"] = 0.0
        low_result = evaluate(low, config)["evaluation_result"]
        self.assertEqual(low_result["resolved_profile"], "adaptive")
        self.assertIsNotNone(low_result["reduction_tendency"])

        high = context.base_packet()
        high["stance"].update({"commitment": 1.0, "public_commitment": 1.0, "volition": 1.0, "self_relevance": 1.0})
        high["user_pressure"] = 1.0
        high_result = evaluate(high, config)["evaluation_result"]
        self.assertEqual(high_result["resolved_profile"], "dissonance_reduction")
        self.assertGreaterEqual(high_result["reduction_tendency"], config["evaluator"]["mixed"]["reduction_cutoff"])

    def test_baseline_profile_shapes_nothing(self):
        config = context.config_with(skill={"profile": "baseline"})
        result = evaluate(config=config)["evaluation_result"]
        self.assertEqual(result["recommended_strategy"], "none")
        self.assertEqual(result["fired_rule_id"], "baseline_no_shaping")

    def test_reduction_branch_is_flagged_as_fidelity_not_advice(self):
        config = context.config_with(skill={"profile": "dissonance_reduction"})
        packet = context.base_packet()
        packet["stance"]["commitment"] = 0.90
        # Strong evidence is required to reach R09: R07 (trivialize) claims the
        # mid band first, which is itself the point of an ordered rule list.
        packet["evidence"][0].update(
            {"credibility": 0.90, "relevance": 0.90, "recency": 0.90, "independence": 0.90, "consistency": 0.90}
        )
        evaluation = evaluate(packet, config)
        self.assertEqual(evaluation["evaluation_result"]["recommended_strategy"], "deny_evidence")
        self.assertEqual(evaluation["evaluation_result"]["fired_rule_id"], "R09_reduction_deny")
        self.assertEqual(evaluation["response_plan"]["branch"], "dissonance_reduction")
        self.assertIn("fidelity_not_advice", evaluation["response_plan"]["constraints"])
        self.assertIn("discount_requires_checkable_reason", evaluation["response_plan"]["constraints"])
        self.assertTrue(any("失调削减" in caveat or "dissonance reduction" in caveat for caveat in evaluation["evaluation_result"]["caveats"]))

    def test_reduction_mid_band_trivializes_before_denying(self):
        config = context.config_with(skill={"profile": "dissonance_reduction"})
        packet = context.base_packet()
        packet["stance"]["commitment"] = 0.90
        evaluation = evaluate(packet, config)
        self.assertEqual(evaluation["evaluation_result"]["recommended_strategy"], "trivialize")
        self.assertEqual(evaluation["evaluation_result"]["fired_rule_id"], "R07_reduction_trivialize")

    def test_planned_change_flag_matches_the_strategy(self):
        """``planned_change`` is a function of the strategy, and the test says so.

        The name matters: this value is the engine's intention, derived from the
        routed strategy string, so it carries no information about the reply. The
        assertion below is a statement about the rule table, not a measurement.
        """
        by_strategy = {}
        for profile in ("adaptive", "dissonance_reduction"):
            config = context.config_with(skill={"profile": profile})
            for commitment, e_score_evidence in ((0.9, 0.2), (0.5, 0.5), (0.9, 0.95), (0.2, 0.95)):
                packet = context.base_packet()
                packet["stance"]["commitment"] = commitment
                packet["evidence"][0].update(
                    {"credibility": e_score_evidence, "relevance": e_score_evidence, "consistency": e_score_evidence}
                )
                plan = evaluate(packet, config)["response_plan"]
                by_strategy.setdefault(plan["strategy"], plan["stance_update"]["planned_change"])

        for strategy, planned in by_strategy.items():
            with self.subTest(strategy=strategy):
                if strategy in ("qualify", "recalibrate", "reduce_commitment"):
                    self.assertTrue(planned, f"{strategy} should plan a stance change")
                elif strategy in ("maintain_with_caveat", "deny_evidence", "trivialize", "rationalize", "hold_under_pressure"):
                    self.assertFalse(planned, f"{strategy} must not plan a stance change")

    def test_the_old_changed_key_is_gone(self):
        """The rename is load-bearing, so a silent reintroduction must fail loudly."""
        plan = evaluate()["response_plan"]
        self.assertIn("planned_change", plan["stance_update"])
        self.assertNotIn("changed", plan["stance_update"])


class TestPressureModerator(unittest.TestCase):
    def test_pressure_is_flagged_but_absent_from_the_index(self):
        packet = context.base_packet(user_pressure=0.85)
        detection = build_detection(packet, context.BASE_CONFIG)
        result = build_evaluation(detection, packet, context.BASE_CONFIG)["evaluation_result"]
        self.assertTrue(result["user_pressure_flag"])
        self.assertNotIn("user_pressure", detection["conflict_event"]["terms"])

    def test_pressure_flag_threshold_is_configurable(self):
        config = context.config_with(evaluator={"pressure_flag_threshold": 0.99})
        packet = context.base_packet(user_pressure=0.85)
        detection = build_detection(packet, config)
        result = build_evaluation(detection, packet, config)["evaluation_result"]
        self.assertFalse(result["user_pressure_flag"])


class TestStageRefusal(unittest.TestCase):
    def test_withheld_arms_refuse_to_evaluate(self):
        for mode in ("off", "detect_only", "placebo"):
            with self.subTest(mode=mode):
                config = context.config_with(skill={"mode": mode})
                packet = context.base_packet()
                detection = build_detection(packet, config)
                with self.assertRaises(StageError):
                    build_evaluation(detection, packet, config)


class TestEvaluationSchema(unittest.TestCase):
    def test_output_satisfies_the_published_schema(self):
        evaluation = evaluate()
        errors = validate(load_schema("evaluation"), evaluation)
        self.assertEqual(errors, [], f"evaluation schema violations: {errors}")

    def test_baseline_output_satisfies_the_schema(self):
        config = context.config_with(skill={"profile": "baseline"})
        evaluation = evaluate(config=config)
        errors = validate(load_schema("evaluation"), evaluation)
        self.assertEqual(errors, [], f"evaluation schema violations: {errors}")


if __name__ == "__main__":
    unittest.main()
