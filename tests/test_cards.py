"""Tests for the transparency cards.

The card is the only surface a user reads, so a claim that lives in the log but
not on the card is, from the user's side, not reported at all. These tests hold
the card to the project's own labelling rules.

Since v0.4.0 the same facts are rendered in two styles. That is a presentation
choice and never a licence to drop a construct label, so every labelling rule
below is asserted for **both** styles: the vocabulary differs, the invariant does
not. A test that only checked the style it was written against is exactly how a
readability rewrite would silently delete the gate label.

The bug the original tests guarded: `detect_card` chose its headline between
`indeterminacy` and `dissonance` only. A gated event has `channel == "none"`, so it
fell through to the dissonance headline, while the `channel:` line was omitted at
the same time. The reader saw "认知失调相关冲突张力" over a capped 0.40 and no
indication that the cap had fired - which contradicts `SKILL.md` ("the event is not
dissonance. Do not report it as such") and hides the gate that Study 1's Claim 1
rests on.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import context  # noqa: F401  (side effect: puts scripts/ on sys.path)

from cds_cards import detect_brief, detect_card, evaluation_card, guard_card, response_card
from cds_evaluator import build_evaluation
from cds_guard import run_guard
from cds_index import build_detection

REPO_ROOT = Path(__file__).resolve().parent.parent

CARD_STYLES = ("plain", "technical")

# Card vocabulary that asserts the construct. A gated event must not carry it.
GATE_HEADLINE = "已检测到冲突，未计入失调"
GATE_HEADLINE_EN = "conflict detected, not counted as dissonance"

#: Per-style wording for the same claim. Keeping this table explicit is the point:
#: a reader can see, side by side, that each style has a way of saying "this is
#: dissonance", "this is not", and "the index was capped".
STYLE = {
    "plain": {
        "dissonance_assertion": "被冲击的是我自己选定并说过的判断",
        "indeterminacy_assertion": "发现证据之间自相矛盾（不是认知失调）",
        "score_line": "冲突检测大小",
        "margin_line": "评分可动范围",
        "capped": "已封顶",
        "not_dissonance": "不计入失调",
    },
    "technical": {
        "dissonance_assertion": "认知失调相关冲突张力",
        "indeterminacy_assertion": "证据不确定性（非失调）",
        "score_line": "张力指数",
        "margin_line": "评分可动范围",
        "capped": "已封顶",
        "not_dissonance": "未计入失调",
    },
}


def style_config(style: str, **skill):
    """The shipped config in one card style, with optional skill overrides."""
    return context.config_with(skill=skill, transparency={"card_style": style})


def gated_detection(config=None):
    """A packet whose stance was assigned, so the volition floor caps the index."""
    packet = context.base_packet()
    # volition * self_relevance = 0.10, well below the 0.30 floor.
    packet["stance"]["volition"] = 0.20
    packet["stance"]["self_relevance"] = 0.50
    return build_detection(packet, config or context.BASE_CONFIG)


class TestGatedDetectionCard(unittest.TestCase):
    """A capped conflict must be labelled as capped, on its face."""

    def test_gate_is_applied_in_this_fixture(self):
        """Guard the fixture: if the gate stops firing, the rest proves nothing."""
        detection = gated_detection()
        self.assertTrue(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(detection["tension_result"]["channel"], "none")
        self.assertEqual(detection["tension_result"]["tension"], 0.40)

    def test_headline_does_not_claim_dissonance(self):
        for style in CARD_STYLES:
            with self.subTest(style=style):
                card = detect_card(gated_detection(), style_config(style))
                self.assertIn(GATE_HEADLINE, card)
                self.assertNotIn(STYLE[style]["dissonance_assertion"], card)

    def test_card_never_claims_the_dissonance_channel(self):
        """The plain style asserts free choice in words; the technical one by name."""
        for style in CARD_STYLES:
            with self.subTest(style=style):
                card = detect_card(gated_detection(), style_config(style))
                self.assertNotIn(STYLE[style]["dissonance_assertion"], card)
                self.assertIn(STYLE[style]["not_dissonance"], card)

    def test_gate_reason_is_stated_verbatim(self):
        """The engine's own explanation must appear, not a re-worded parallel."""
        detection = gated_detection()
        detail = detection["conflict_event"]["gate"]["detail"]
        self.assertTrue(detail)
        for style in CARD_STYLES:
            with self.subTest(style=style):
                self.assertIn(detail, detect_card(detection, style_config(style)))

    def test_capped_and_raw_index_are_both_visible(self):
        """The cap must not masquerade as the value the ratings produced."""
        detection = gated_detection()
        raw = detection["conflict_event"]["raw_index"]
        self.assertGreaterEqual(raw, 0.55)  # would have fired without the gate
        for style in CARD_STYLES:
            with self.subTest(style=style):
                card = detect_card(detection, style_config(style))
                self.assertIn(f"{raw:.2f}", card)
                self.assertIn(STYLE[style]["capped"], card)
                self.assertIn("0.40", card)

    def test_english_card_labels_the_gate_too(self):
        config = style_config("plain", language="en")
        detection = gated_detection(config)
        card = detect_card(detection, config)
        self.assertIn(GATE_HEADLINE_EN, card)
        self.assertNotIn("cognitive-dissonance-related conflict tension", card)

    def test_non_numeric_cards_still_label_the_gate(self):
        """`numeric_cards: false` removes figures, never the gate label."""
        for style in CARD_STYLES:
            with self.subTest(style=style):
                config = style_config(style, numeric_cards=False)
                card = detect_card(gated_detection(config), config)
                self.assertIn(GATE_HEADLINE, card)
                self.assertNotIn(STYLE[style]["score_line"] + "：0", card)
                self.assertNotIn("0.40", card)

    def test_non_numeric_capped_event_is_not_described_as_clearing_the_bar(self):
        """With the figure gone the word is all the reader has, so it must be right.

        A capped index sits below the level threshold. Rendering that as "just over
        the bar" would assert the opposite of what the engine computed, and this is
        the one variant where nothing else on the card corrects it.
        """
        config = style_config("plain", numeric_cards=False)
        card = detect_card(gated_detection(config), config)
        self.assertIn("未达门槛", card)
        self.assertNotIn("刚好过线", card)


class TestUngatedCardsAreUnchanged(unittest.TestCase):
    """The fix must not disturb the two cards that were already right."""

    def test_freely_chosen_stance_keeps_the_dissonance_label(self):
        detection = build_detection(context.base_packet(), context.BASE_CONFIG)
        self.assertFalse(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(detection["tension_result"]["channel"], "dissonance")
        for style in CARD_STYLES:
            with self.subTest(style=style):
                card = detect_card(detection, style_config(style))
                self.assertIn(STYLE[style]["dissonance_assertion"], card)
                self.assertNotIn(GATE_HEADLINE, card)
                self.assertNotIn(STYLE[style]["capped"], card)

    def test_indeterminacy_card_keeps_its_own_label(self):
        """When the gate is not involved, indeterminacy keeps its own headline.

        The index is held below the alert threshold on purpose: `channel` prefers
        `dissonance` whenever the dissonance channel fires, so an indeterminacy
        headline is only reachable when it does not. A stance is supplied so that
        `volition_self` clears the floor and the gate stays out of the way.
        """
        packet = context.base_packet(
            relation={"type": "evidence_vs_evidence", "opposition": 0.20, "specificity": 0.20},
            evidence_conflict_unresolved=0.85,
        )
        detection = build_detection(packet, context.BASE_CONFIG)
        self.assertFalse(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(detection["tension_result"]["channel"], "indeterminacy")
        for style in CARD_STYLES:
            with self.subTest(style=style):
                card = detect_card(detection, style_config(style))
                self.assertIn(STYLE[style]["indeterminacy_assertion"], card)
                self.assertNotIn(GATE_HEADLINE, card)

    def test_stanceless_evidence_conflict_is_gated_and_labelled_so(self):
        """No stance means no free choice, so the gate caps it - and says so.

        The indeterminacy channel is itself ungated, so this event still reports its
        indeterminacy; what the gate removes is any dissonance reading.
        """
        packet = context.base_packet(
            relation={"type": "evidence_vs_evidence", "opposition": 0.80, "specificity": 0.70},
            evidence_conflict_unresolved=0.85,
        )
        packet["stance"] = None
        detection = build_detection(packet, context.BASE_CONFIG)
        self.assertTrue(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(detection["tension_result"]["channel"], "indeterminacy")
        for style in CARD_STYLES:
            with self.subTest(style=style):
                card = detect_card(detection, style_config(style))
                self.assertIn(GATE_HEADLINE, card)
                self.assertNotIn(STYLE[style]["dissonance_assertion"], card)
                # The ungated channel still reports. In technical style that is the
                # indeterminacy figure; in plain style it is the sentence naming the
                # evidence as the thing that clashes, which is the only form of the
                # figure a reader can act on anyway. This packet names a single
                # evidence item, so there is no second source to label.
                if style == "technical":
                    self.assertIn("不确定度", card)
                else:
                    self.assertIn("证据之间互相冲突", card)
                    self.assertIn("观点1", card)

    def test_sub_threshold_ungated_card_is_still_silent(self):
        """A genuinely low-index event is not a gated event and must not say so."""
        packet = context.base_packet(
            relation={"type": "evidence_vs_stance", "opposition": 0.20, "specificity": 0.10},
        )
        packet["stance"]["commitment"] = 0.10
        detection = build_detection(packet, context.BASE_CONFIG)
        self.assertFalse(detection["conflict_event"]["gate"]["applied"])
        self.assertLess(detection["tension_result"]["tension"], 0.55)
        for style in CARD_STYLES:
            with self.subTest(style=style):
                card = detect_card(detection, style_config(style))
                self.assertNotIn(GATE_HEADLINE, card)
                self.assertNotIn(STYLE[style]["capped"], card)


class TestClaimsAreNamed(unittest.TestCase):
    """The card must say *what* the conflict is, not only how large it scored."""

    def test_detect_card_names_both_sides(self):
        for style in CARD_STYLES:
            with self.subTest(style=style):
                detection = build_detection(context.base_packet(), style_config(style))
                card = detect_card(detection, style_config(style))
                self.assertIn("X is reliable here", card)
                self.assertIn("X fails in most deployments", card)

    def test_evidence_vs_evidence_gets_two_source_labels(self):
        packet = context.base_packet(
            relation={"type": "evidence_vs_evidence", "opposition": 0.70, "specificity": 0.70},
            evidence_conflict_unresolved=0.85,
            evidence=[
                {"id": "ev_001", "claim": "第一份报告称延迟下降", "carries_conflict": True, "novelty": 0.6,
                 "relevance": 0.8, "credibility": 0.6, "recency": 0.6, "independence": 0.3,
                 "consistency": 0.4, "quote": "latency fell"},
                {"id": "ev_002", "claim": "第二份报告称延迟上升", "carries_conflict": True, "novelty": 0.6,
                 "relevance": 0.8, "credibility": 0.6, "recency": 0.6, "independence": 0.3,
                 "consistency": 0.4, "quote": "latency rose"},
            ],
        )
        card = detect_card(build_detection(packet, context.BASE_CONFIG), context.BASE_CONFIG)
        self.assertIn("来源一的说法", card)
        self.assertIn("来源二的说法", card)

    def test_long_claims_are_excerpted_not_dropped(self):
        long_claim = "很长的一段主张。" * 40
        packet = context.base_packet()
        packet["stance"]["claim"] = long_claim
        card = detect_card(build_detection(packet, context.BASE_CONFIG), context.BASE_CONFIG)
        self.assertIn("…", card)
        self.assertLess(max(len(line) for line in card.splitlines()), 200)

    def test_claims_absent_from_the_packet_omit_the_line(self):
        """A packet that names no evidence must not produce an invented claim."""
        packet = context.base_packet()
        packet.pop("evidence")
        detection = build_detection(packet, context.BASE_CONFIG)
        self.assertIsNone(detection["conflict_event"]["claims"]["b"])
        card = detect_card(detection, context.BASE_CONFIG)
        self.assertNotIn("观点2", card)


class TestGuardCard(unittest.TestCase):
    """The guard card is the only surface that decides whether anything else runs."""

    def guard_result(self, packet=None, config=None, history=None):
        return run_guard(
            packet or context.base_packet(),
            config or context.BASE_CONFIG,
            history=history or {"current_turn": 1, "surfaces_count": 0, "last_surface_turn": None, "dismissed": []},
        )

    def test_silent_renders_nothing_at_all(self):
        """Empty is the correct rendering: invisibility is the feature."""
        packet = context.base_packet(relation={"type": "none", "opposition": 0.0, "specificity": 0.0})
        packet.pop("evidence")
        packet["stance"] = None
        result = self.guard_result(packet)
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(guard_card(result, context.BASE_CONFIG), "")

    def test_surface_states_the_conflict_and_asks(self):
        result = self.guard_result()
        self.assertEqual(result["decision"], "surface")
        self.assertTrue(result["asks_user"])
        card = guard_card(result, context.BASE_CONFIG)
        self.assertIn("观点1", card)
        self.assertIn("观点2", card)
        self.assertIn("X is reliable here", card)
        self.assertIn("冲突大小", card)
        self.assertIn("是否进入评估？", card)
        self.assertIn("处理", card)
        self.assertIn("忽略", card)

    def test_surface_card_shows_the_span_the_stance_was_read_off(self):
        """v0.5.0. The card names the source span, not just the claim.

        The failure this exists to prevent: a card asserting that "what I said
        earlier" was contradicted, on a turn where nothing had been said. Printing
        the anchor puts the extraction in front of the reader, so a claim the tool
        invented is visible as one rather than being asserted with the engine's
        authority behind it.
        """
        result = self.guard_result()
        card = guard_card(result, context.BASE_CONFIG)
        self.assertIn("依据原文", card)
        self.assertIn("turn 1: I said X is reliable here", card)

    def test_a_gated_card_does_not_echo_an_anchor_it_does_not_have(self):
        packet = context.base_packet()
        packet["stance"]["volition"] = 0.0
        packet["stance"]["self_relevance"] = 0.0
        result = self.guard_result(packet)
        card = guard_card(result, context.BASE_CONFIG)
        self.assertNotIn("依据原文", card)

    def test_placebo_card_carries_no_conflict_content(self):
        config = context.config_with(skill={"mode": "placebo"})
        result = self.guard_result(config=config)
        card = guard_card(result, config)
        self.assertNotIn("X is reliable here", card)
        self.assertNotIn("X fails in most deployments", card)
        self.assertIn("不提供冲突内容", card)

    def test_auto_policy_does_not_ask_the_user(self):
        config = context.config_with(guard={"policy": "auto"})
        result = self.guard_result(config=config)
        self.assertEqual(result["decision"], "surface")
        self.assertFalse(result["asks_user"])
        card = guard_card(result, config)
        self.assertNotIn("是否进入评估？", card)
        # It still renders: the loop is about to run without a decision, and the card
        # is what tells the user that.
        self.assertIn("已自动进入评估", card)

    def test_log_only_policy_renders_nothing(self):
        """'Record, never show' has to be a property of the renderer, not a promise."""
        config = context.config_with(guard={"policy": "log_only"})
        result = self.guard_result(config=config)
        self.assertEqual(result["decision"], "surface")
        self.assertEqual(result["next_action"], "log_only")
        self.assertEqual(guard_card(result, config), "")

    def test_detect_only_arm_renders_nothing_and_never_asks(self):
        """The arm's own card comes from `detect`; the guard stays quiet here."""
        config = context.config_with(skill={"mode": "detect_only"})
        result = self.guard_result(config=config)
        self.assertFalse(result["asks_user"])
        self.assertEqual(result["next_action"], "log_only")
        self.assertEqual(guard_card(result, config), "")

    def test_technical_style_adds_the_decomposition(self):
        config = style_config("technical")
        card = guard_card(self.guard_result(config=config), config)
        self.assertIn("索引分解", card)
        self.assertIn("opposition", card)

    def test_plain_style_hides_the_identifiers(self):
        card = guard_card(self.guard_result(), context.BASE_CONFIG)
        self.assertNotIn("evidence_vs_stance", card)
        self.assertNotIn("索引分解", card)


class TestPlainCardReadability(unittest.TestCase):
    """The plain style has to be readable, and readable is testable in part."""

    def evaluation(self, config=None):
        config = config or context.BASE_CONFIG
        packet = context.base_packet()
        detection = build_detection(packet, config)
        return build_evaluation(detection, packet, config)

    def test_evaluation_card_shows_each_evidence_dimension_with_its_weight(self):
        card = evaluation_card(self.evaluation(), context.BASE_CONFIG)
        for dimension in ("相关性", "可信度", "时效性", "独立性", "一致性"):
            with self.subTest(dimension=dimension):
                self.assertIn(dimension, card)
        self.assertIn("权重 25%", card)
        self.assertIn("改口代价", card)
        self.assertIn("建议", card)

    def test_evaluation_card_hides_weights_numbers_when_asked(self):
        config = style_config("plain", numeric_cards=False)
        card = evaluation_card(self.evaluation(config), config)
        self.assertIn("权重 25%", card)  # weights are structure, not a score
        self.assertNotIn("0.60", card)

    def test_response_card_names_the_strategy_in_plain_words(self):
        card = response_card(self.evaluation(), context.BASE_CONFIG)
        self.assertIn("我采用的应对策略", card)
        self.assertIn("限定原立场", card)
        self.assertIn("这是什么策略", card)
        self.assertIn("你会在回复里看到我", card)
        # The plain card prints the moves, not the act codes.
        for code in ("mark_conflict", "acknowledge_counterevidence", "give_verification_path"):
            with self.subTest(code=code):
                self.assertNotIn(code, card)

    def test_response_card_states_whether_the_stance_moves(self):
        card = response_card(self.evaluation(), context.BASE_CONFIG)
        self.assertIn("立场会不会变：会", card)
        self.assertIn("下一步", card)

    def test_reduction_branch_is_labelled_and_flagged_as_simulation(self):
        config = context.config_with(
            skill={"profile": "dissonance_reduction"}, transparency={"card_style": "plain"}
        )
        card = response_card(self.evaluation(config), config)
        self.assertIn("失调削减型", card)
        self.assertIn("不代表系统建议", card)

    def test_withhold_acts_card_keeps_the_branch_hidden(self):
        config = context.config_with(
            skill={"mode": "withhold_acts"}, transparency={"card_style": "plain"}
        )
        card = response_card(self.evaluation(config), config)
        self.assertIn("本轮不给出行为指令", card)
        self.assertNotIn("审慎校准型", card)
        self.assertNotIn("失调削减型", card)

    def test_detect_brief_is_one_line(self):
        packet = context.base_packet()
        line = detect_brief(build_detection(packet, context.BASE_CONFIG), context.BASE_CONFIG)
        self.assertEqual(len(line.splitlines()), 1)
        self.assertIn("已确认冲突", line)

    def test_guard_card_is_shorter_than_the_detection_card(self):
        """The screening surface must not cost more attention than the full one."""
        packet = context.base_packet()
        detection = build_detection(packet, context.BASE_CONFIG)
        result = run_guard(packet, context.BASE_CONFIG, history={"current_turn": 1, "surfaces_count": 0, "last_surface_turn": None, "dismissed": []})
        guard_text = guard_card(result, context.BASE_CONFIG)
        detect_text = detect_card(detection, context.BASE_CONFIG)
        self.assertLess(len(guard_text), len(detect_text))


class TestDocumentedFigures(unittest.TestCase):
    """The card claims and the documented figures must stay executable claims."""

    def test_check_examples_passes_including_the_test_count(self):
        """`check_examples.py` guards the README's figures, so it must itself be run.

        CI calls the script, and this test makes it part of the suite as well: a
        drift between the documented test count and `tests/` fails once, in the
        place a contributor is already looking.
        """
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "check_examples.py")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_detection_card_documents_the_gate_label(self):
        """The new headline must be reachable by a reader of `references/cards.md`.

        A label that exists only in the code and in tests is not a documented
        behaviour; the card reference is what a rater or a reviewer reads.
        """
        text = (REPO_ROOT / "references" / "cards.md").read_text(encoding="utf-8")
        self.assertIn("未计入失调", text)
        self.assertIn("门控", text)

    def test_cards_reference_documents_both_styles(self):
        """`card_style` is a config surface, so it has to be documented as one."""
        text = (REPO_ROOT / "references" / "cards.md").read_text(encoding="utf-8")
        self.assertIn("card_style", text)
        self.assertIn("plain", text)
        self.assertIn("technical", text)

    def test_guard_card_is_documented(self):
        text = (REPO_ROOT / "references" / "cards.md").read_text(encoding="utf-8")
        self.assertIn("是否进入评估", text)

    def test_examples_document_the_claim_roles(self):
        """The role vocabulary is public, so the shipped example must show it."""
        payload = json.loads((REPO_ROOT / "examples" / "packet_evidence_vs_stance.json").read_text(encoding="utf-8"))
        detection = build_detection(payload, context.BASE_CONFIG)
        claims = detection["conflict_event"]["claims"]
        self.assertEqual(claims["a"]["role"], "stance")
        self.assertEqual(claims["b"]["role"], "evidence")


if __name__ == "__main__":
    unittest.main()
