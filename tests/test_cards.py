"""Tests for the transparency cards.

The card is the only surface a user reads, so a claim that lives in the log but
not on the card is, from the user's side, not reported at all. These tests hold
the card to the project's own labelling rules.

The bug they guard: `detect_card` chose its headline between `indeterminacy` and
`dissonance` only. A gated event has `channel == "none"`, so it fell through to
the dissonance headline, while the `channel:` line was omitted at the same time.
The reader saw "认知失调相关冲突张力" over a capped 0.40 and no indication that
the cap had fired — which contradicts `SKILL.md` ("the event is not dissonance.
Do not report it as such") and hides the gate that Study 1's Claim 1 rests on.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import context  # noqa: F401  (side effect: puts scripts/ on sys.path)

from cds_cards import detect_card
from cds_index import build_detection

REPO_ROOT = Path(__file__).resolve().parent.parent

# Card vocabulary that asserts the construct. A gated event must not carry it.
DISSONANCE_CHANNEL_TEXT = "失调通道（需要自主选择的立场）"
DISSONANCE_CHANNEL_TEXT_EN = "dissonance channel (requires a freely chosen stance)"
GATE_HEADLINE = "已检测到冲突，未计入失调"
GATE_HEADLINE_EN = "conflict detected, not counted as dissonance"


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
        card = detect_card(gated_detection(), context.BASE_CONFIG)
        headline = card.splitlines()[1]
        self.assertIn(GATE_HEADLINE, headline)
        self.assertNotIn("认知失调相关冲突张力", headline)

    def test_card_never_claims_the_dissonance_channel(self):
        card = detect_card(gated_detection(), context.BASE_CONFIG)
        self.assertNotIn(DISSONANCE_CHANNEL_TEXT, card)

    def test_gate_reason_is_stated_verbatim(self):
        """The engine's own explanation must appear, not a re-worded parallel."""
        detection = gated_detection()
        detail = detection["conflict_event"]["gate"]["detail"]
        self.assertTrue(detail)
        self.assertIn(detail, detect_card(detection, context.BASE_CONFIG))

    def test_capped_and_raw_index_are_both_visible(self):
        """The cap must not masquerade as the value the ratings produced."""
        detection = gated_detection()
        raw = detection["conflict_event"]["raw_index"]
        self.assertGreaterEqual(raw, 0.55)  # would have fired without the gate
        card = detect_card(detection, context.BASE_CONFIG)
        self.assertIn(f"{raw:.2f}", card)
        self.assertIn("已封顶", card)
        self.assertIn("0.40", card)

    def test_english_card_labels_the_gate_too(self):
        config = context.config_with(skill={"language": "en"})
        detection = gated_detection(config)
        card = detect_card(detection, config)
        self.assertIn(GATE_HEADLINE_EN, card)
        self.assertNotIn(DISSONANCE_CHANNEL_TEXT_EN, card)
        self.assertNotIn("cognitive-dissonance-related conflict tension", card)

    def test_non_numeric_cards_still_label_the_gate(self):
        """`numeric_cards: false` removes figures, never the gate label."""
        config = context.config_with(skill={"numeric_cards": False})
        card = detect_card(gated_detection(config), config)
        self.assertIn(GATE_HEADLINE, card)
        self.assertNotIn("张力指数", card)
        self.assertNotIn("0.40", card)


class TestUngatedCardsAreUnchanged(unittest.TestCase):
    """The fix must not disturb the two cards that were already right."""

    def test_freely_chosen_stance_keeps_the_dissonance_label(self):
        detection = build_detection(context.base_packet(), context.BASE_CONFIG)
        self.assertFalse(detection["conflict_event"]["gate"]["applied"])
        self.assertEqual(detection["tension_result"]["channel"], "dissonance")
        card = detect_card(detection, context.BASE_CONFIG)
        self.assertIn("认知失调相关冲突张力", card)
        self.assertIn(DISSONANCE_CHANNEL_TEXT, card)
        self.assertNotIn(GATE_HEADLINE, card)
        self.assertNotIn("已封顶", card)

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
        card = detect_card(detection, context.BASE_CONFIG)
        self.assertIn("证据不确定性（非失调）", card)
        self.assertNotIn("认知失调相关冲突张力", card)
        self.assertNotIn(GATE_HEADLINE, card)

    def test_stanceless_evidence_conflict_is_gated_and_labelled_so(self):
        """No stance means no free choice, so the gate caps it — and says so.

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
        card = detect_card(detection, context.BASE_CONFIG)
        self.assertIn(GATE_HEADLINE, card)
        self.assertNotIn(DISSONANCE_CHANNEL_TEXT, card)
        self.assertIn("不确定度", card)  # the ungated channel still reports

    def test_sub_threshold_ungated_card_is_still_silent(self):
        """A genuinely low-index event is not a gated event and must not say so."""
        packet = context.base_packet(
            relation={"type": "evidence_vs_stance", "opposition": 0.20, "specificity": 0.10},
        )
        packet["stance"]["commitment"] = 0.10
        detection = build_detection(packet, context.BASE_CONFIG)
        self.assertFalse(detection["conflict_event"]["gate"]["applied"])
        self.assertLess(detection["tension_result"]["tension"], 0.55)
        card = detect_card(detection, context.BASE_CONFIG)
        self.assertNotIn(GATE_HEADLINE, card)
        self.assertNotIn("已封顶", card)


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


if __name__ == "__main__":
    unittest.main()
