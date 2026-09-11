"""Tests for the extraction rule and the third channel (v0.5.0).

Two claims, and the tests exist because both were violated in use:

1. **The agent has no opinions of its own.** Every position it reasons about is
   read off a span that is already in the context. A packet that names a position
   and cannot point at one is capped by the ``anchor_required`` gate, and the guard
   refuses to interrupt a user for it. The failure this replaces was observed: a
   first turn, nothing asserted anywhere, and a card announcing that "what I said
   earlier" had been contradicted.
2. **A mainstream value norm is not dissonance.** It is the one sanctioned
   exemption from the extraction rule - a norm cannot be read out of a conversation
   that does not mention it - and it is not indeterminacy either, because the
   direction is fully determinate. It therefore travels on its own channel, is
   labelled as a norm conflict, and is never reported as cognitive dissonance.
"""

from __future__ import annotations

import contextlib
import io
import unittest

import context

import cds
from cds_cards import ask_payload, audit_line, guard_card
from cds_guard import R_UNANCHORED, R_GATED, run_guard
from cds_index import anchor_missing, is_normative_prior


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cds.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def fresh_history(**overrides) -> dict:
    history = {"current_turn": 1, "surfaces_count": 0, "last_surface_turn": None, "dismissed": []}
    history.update(overrides)
    return history


def unanchored_packet(**overrides):
    packet = context.base_packet(**overrides)
    packet["stance"].pop("anchor", None)
    return packet


def normative_packet(**overrides):
    packet = context.base_packet(**overrides)
    packet["stance"].update(
        {
            "source": "normative_prior",
            "claim": "不得对平民实施暴力",
            "anchor": "基线价值规范：不得对平民实施暴力",
            "normative_basis": "不得对平民实施暴力",
            "volition": 0.0,
            "self_relevance": 0.0,
            "commitment": 0.2,
            "public_commitment": 0.1,
        }
    )
    return packet


class TestAnchorRequirement(unittest.TestCase):
    """A position with no source span is not a position the agent held."""

    def test_anchor_missing_only_bites_on_stance_carrying_types(self):
        self.assertTrue(anchor_missing(unanchored_packet()))
        packet = unanchored_packet(relation={"type": "evidence_vs_evidence"})
        packet.pop("stance")
        self.assertFalse(anchor_missing(packet))

    def test_a_system_prompt_stance_is_exempt(self):
        """The assignment is the span, and the volition floor does the rest.

        A harness that hands the agent a position in writing has produced a
        quotation by definition. What keeps that out of the dissonance channel is
        the free-choice gate, not this rule, and the two must not be conflated.
        """
        packet = unanchored_packet()
        packet["stance"]["source"] = "system_prompt"
        self.assertFalse(anchor_missing(packet))

    def test_the_gate_caps_an_unanchored_stance(self):
        detection = cds.build_detection(unanchored_packet(), context.BASE_CONFIG)
        gate = detection["conflict_event"]["gate"]
        self.assertTrue(gate["applied"])
        self.assertEqual(gate["rule"], "anchor_required")
        self.assertLessEqual(
            detection["tension_result"]["tension"],
            context.BASE_CONFIG["index"]["gates"]["non_dissonant_cap"],
        )
        self.assertEqual(detection["tension_result"]["channel"], "none")

    def test_the_gate_does_not_fire_once_the_span_is_named(self):
        detection = cds.build_detection(context.base_packet(), context.BASE_CONFIG)
        self.assertFalse(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(detection["tension_result"]["channel"], "dissonance")

    def test_the_guard_never_interrupts_a_user_about_an_unanchored_stance(self):
        """The regression that matters, stated as one assertion.

        Every content bar this packet could have cleared, it clears: opposition,
        commitment and free choice are all high. The anchor is the only thing
        missing, and it is the thing that decides whether the card is a finding or
        an invention.
        """
        result = run_guard(unanchored_packet(), context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_UNANCHORED])
        self.assertFalse(result["gated"] and result["channel"] == "dissonance")

    def test_the_anchor_gate_is_checked_before_the_volition_gate(self):
        """Both gates apply here; the recorded reason must be the substantive one.

        A packet with neither an anchor nor a freely chosen stance is reported as
        unanchored, because "there is no evidence this position existed" is a
        stronger and more actionable statement than "it was not freely chosen".
        """
        packet = unanchored_packet()
        packet["stance"]["volition"] = 0.0
        packet["stance"]["self_relevance"] = 0.0
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["reasons"], [R_UNANCHORED])
        self.assertEqual(
            result["detection"]["conflict_event"]["gate"]["rule"], "anchor_required"
        )

    def test_the_requirement_can_be_switched_off_for_reproduction(self):
        config = context.config_with(guard={"require_anchor": False})
        result = run_guard(unanchored_packet(), config, history=fresh_history())
        self.assertEqual(result["decision"], "surface")
        self.assertFalse(result["detection"]["conflict_event"]["gate"]["applied"])

    def test_the_card_reports_the_missing_span(self):
        detection = cds.build_detection(unanchored_packet(), context.BASE_CONFIG)
        self.assertIn(
            "该立场没有可引用的原文出处，无法确认它来自本轮上下文",
            detection["tension_result"]["uncertainty"],
        )

    def test_the_anchor_is_carried_into_the_record(self):
        detection = cds.build_detection(context.base_packet(), context.BASE_CONFIG)
        stance = detection["conflict_event"]["stance"]
        self.assertTrue(stance["anchored"])
        self.assertEqual(stance["anchor"], "turn 1: I said X is reliable here")


class TestInlineScreenRequiresAnAnchor(unittest.TestCase):
    """The bad packet cannot be built by accident through the one-line screen."""

    BASE = [
        "guard",
        "--type", "evs",
        "--screen", "opp=high,commit=high,vol=high,self=high,spec=high,nov=high",
        "--stance", "X 在该场景下是可靠的",
        "--evidence", "新研究显示 X 存在重大缺陷",
        "--no-log",
        "--no-turn-advance",
    ]

    def test_without_an_anchor_the_cli_refuses(self):
        code, out, err = run_cli(*self.BASE)
        self.assertEqual(code, 3)
        self.assertIn("--anchor is required", err)
        self.assertEqual(out.strip(), "")

    def test_the_refusal_names_the_normative_route_as_the_alternative(self):
        _, _, err = run_cli(*self.BASE)
        self.assertIn("normative_prior", err)

    def test_with_an_anchor_the_screen_runs(self):
        code, out, _ = run_cli(*self.BASE, "--anchor", "第 2 轮我说：X 在该场景下是可靠的")
        self.assertEqual(code, 0)
        self.assertIn("CDS_GUARD surface", out)


class TestNormativeChannel(unittest.TestCase):
    """The one exemption, and the reason it is not called dissonance."""

    def test_a_normative_prior_is_recognised(self):
        self.assertTrue(is_normative_prior(normative_packet()))
        self.assertFalse(is_normative_prior(context.base_packet()))

    def test_it_bypasses_the_volition_gate(self):
        """`volition_self` is zero for a norm by construction.

        Without the bypass the gate would cap every norm conflict at 0.40 and the
        channel could never fire - which is the trap the third channel exists to
        avoid, not a reason to lower the gate for everything.
        """
        detection = cds.build_detection(normative_packet(), context.BASE_CONFIG)
        self.assertFalse(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(detection["tension_result"]["channel"], "normative")

    def test_it_is_never_reported_as_dissonance(self):
        detection = cds.build_detection(normative_packet(), context.BASE_CONFIG)
        self.assertEqual(
            detection["tension_result"]["channel_levels"]["dissonance"], "silent"
        )
        self.assertEqual(detection["tension_result"]["channel_levels"]["normative"], "high")

    def test_its_severity_is_the_opposition_not_the_index(self):
        """The index cannot express a norm conflict, and the record says so.

        Two of its five terms are inapplicable: the norm was not chosen and it was
        not asserted by the agent. A perfectly clear norm conflict therefore scores
        about 0.44 on the index - below every threshold it would need to clear -
        while its own channel reads the opposition directly and calls it high.
        """
        detection = cds.build_detection(normative_packet(), context.BASE_CONFIG)
        tension = detection["tension_result"]
        self.assertLess(tension["tension"], tension["threshold_alert"])
        self.assertEqual(tension["level"], "high")
        self.assertEqual(tension["normative"], 0.80)
        self.assertEqual(tension["threshold_normative_alert"], 0.60)
        self.assertEqual(tension["threshold_normative_high"], 0.80)

    def test_the_guard_surfaces_it_on_the_normative_reading(self):
        result = run_guard(normative_packet(), context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["decision"], "surface")
        self.assertEqual(result["channel"], "normative")
        self.assertEqual(result["severity_basis"], "normative_opposition")
        self.assertAlmostEqual(result["severity"], 0.80)
        self.assertLess(result["tension"], result["surface_threshold"])

    def test_a_norm_is_labelled_as_a_norm_on_the_card(self):
        result = run_guard(normative_packet(), context.BASE_CONFIG, history=fresh_history())
        card = guard_card(result, context.BASE_CONFIG)
        self.assertIn("主流规范", card)
        self.assertIn("不按认知失调处理", card)
        self.assertIn("不得对平民实施暴力", card)

    def test_a_mild_norm_conflict_stays_off_the_channel(self):
        packet = normative_packet(relation={"type": "evidence_vs_stance", "opposition": 0.40, "specificity": 0.5})
        detection = cds.build_detection(packet, context.BASE_CONFIG)
        self.assertEqual(detection["tension_result"]["channel"], "none")

    def test_the_channel_can_be_disabled(self):
        config = context.config_with(channels={"normative": {"enabled": False}})
        detection = cds.build_detection(normative_packet(), config)
        self.assertEqual(detection["tension_result"]["channel"], "none")

    def test_a_norm_without_a_named_basis_is_flagged(self):
        packet = normative_packet()
        packet["stance"].pop("normative_basis")
        detection = cds.build_detection(packet, context.BASE_CONFIG)
        self.assertIn(
            "未说明该判断依据的是哪一条主流规范",
            detection["tension_result"]["uncertainty"],
        )

    def test_the_claims_name_the_norm_side_as_a_norm(self):
        detection = cds.build_detection(normative_packet(), context.BASE_CONFIG)
        self.assertEqual(detection["conflict_event"]["claims"]["a"]["role"], "norm")


class TestStopAndAskAndAudit(unittest.TestCase):
    """The two output structures that keep the reply short and the turn stopped."""

    def surface(self, **overrides):
        return run_guard(context.base_packet(**overrides), context.BASE_CONFIG, history=fresh_history())

    def test_the_chooser_says_stop_and_allows_free_text(self):
        ask = ask_payload(self.surface(), context.BASE_CONFIG)
        self.assertTrue(ask["stop"])
        self.assertTrue(ask["free_text"])
        self.assertEqual([option["id"] for option in ask["options"]], ["process", "ignore", "later"])
        self.assertEqual(ask["question"], "是否进入评估？")

    def test_every_option_carries_its_own_explanation(self):
        """The card can stay short because the chooser carries the detail."""
        ask = ask_payload(self.surface(), context.BASE_CONFIG)
        for option in ask["options"]:
            with self.subTest(option=option["id"]):
                self.assertTrue(option["description"])
                self.assertFalse(option["description"].startswith("·"))

    def test_a_silent_decision_has_nothing_to_ask(self):
        packet = context.base_packet(relation={"type": "none", "opposition": 0.0, "specificity": 0.0})
        packet.pop("evidence")
        packet["stance"] = None
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(ask_payload(result, context.BASE_CONFIG), {})

    def test_the_audit_line_names_the_event_and_the_log(self):
        note = audit_line(self.surface(), context.BASE_CONFIG)
        self.assertTrue(note.startswith("CDS 已记录"))
        self.assertIn("cds_evt_", note)
        self.assertIn("logs/cds_skill.jsonl", note)
        self.assertEqual(len(note.splitlines()), 1)

    def test_the_audit_line_can_be_silenced(self):
        config = context.config_with(transparency={"audit_note": "off"})
        self.assertEqual(audit_line(self.surface(), config), "")

    def test_the_ask_output_carries_both_structures(self):
        code, out, _ = run_cli(*self._ask_args())
        self.assertEqual(code, 0)
        self.assertIn("CDS_ASK ", out)
        self.assertIn("CDS_AUDIT CDS 已记录", out)
        # The card comes first: the human-readable part is what the user reads,
        # and the two machine lines are instructions to the host model.
        self.assertLess(out.index("是否进入评估？"), out.index("CDS_ASK "))

    @staticmethod
    def _ask_args():
        return [
            "guard",
            "--type", "evs",
            "--screen", "opp=high,commit=high,vol=high,self=high,spec=high,nov=high",
            "--stance", "X 在该场景下是可靠的",
            "--anchor", "第 2 轮我说：X 在该场景下是可靠的",
            "--evidence", "新研究显示 X 在主要使用场景下存在重大缺陷",
            "--ask",
            "--no-log",
            "--no-turn-advance",
        ]

    def test_stop_and_ask_can_be_turned_off(self):
        """The config knob is live, not decorative.

        A key nothing reads makes the switch look live while the behaviour stays
        fixed, which is the failure mode `thresholds_by_type` is documented
        against. With the knob off the card is still shown - the user step is not
        withheld - but the host model is no longer told to stop the turn.
        """
        args = self._ask_args() + ["--set", "guard.stop_and_ask=false"]
        code, out, _ = run_cli(*args)
        self.assertEqual(code, 0)
        self.assertNotIn("CDS_ASK ", out)
        self.assertNotIn("STOP", out)
        self.assertIn("wait for the user decision", out)
        self.assertIn("是否进入评估？", out)


if __name__ == "__main__":
    unittest.main()
