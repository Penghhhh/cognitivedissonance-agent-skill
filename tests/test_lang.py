"""Tests for v0.5.1: the runtime language follows the conversation.

Two properties, and both are tested here because both were broken:

1. **The language is resolved per turn, not pinned in the config.** An explicit
   ``--lang`` wins, then the packet's own text, then whatever this run already
   resolved, then the fallback. A pinned ``skill.language`` still wins over
   everything except ``--lang``, because for a study the language is a controlled
   factor and not a convenience.
2. **A card rendered in English contains no Chinese.** This is the test the v0.4.0
   English run would have failed: the string tables were complete, but the card
   banners, the claim labels and the key-value separators were inline f-strings, so
   an English card still printed `【CDS｜detection】`, `观点1（...）` and full-width
   colons. Enumerating every card and both styles is the only way that stays fixed.
"""

from __future__ import annotations

import contextlib
import io
import re
import unittest

import context

import cds
from cds_cards import (
    all_cards,
    ask_payload,
    audit_line,
    detect_brief,
    detect_card,
    evaluation_card,
    guard_card,
    response_card,
)
from cds_lang import detect_language, resolve_language
from cds_guard import run_guard

#: Any CJK ideograph, plus the full-width punctuation that leaked with it. The
#: full-width brackets and colons are the part a naive check misses: they are not
#: letters, so a "no Chinese characters" assertion walks straight past them.
CJK_OR_FULLWIDTH = re.compile(
    r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef\u3400-\u4dbf]"
)

EN_PACKET_OVERRIDES = {
    "stance": {
        "claim": "X is reliable in this deployment",
        "anchor": "turn 2: I said X is reliable in this deployment",
        "source": "prior_conversation",
    },
    "relation": {
        "type": "evidence_vs_stance",
        "opposition": 0.80,
        "specificity": 0.60,
        "rationale": "the stance says X is reliable, the paper says it is not",
    },
}

#: The shared fixture is written in English, so a Chinese packet has to say so.
ZH_PACKET_OVERRIDES = {
    "stance": {
        "claim": "该方案在当前规模下是可靠的",
        "anchor": "第 3 轮我说：该方案在当前规模下是可靠的",
        "source": "prior_conversation",
    },
    "relation": {
        "type": "evidence_vs_stance",
        "opposition": 0.80,
        "specificity": 0.60,
        "rationale": "立场称该方案可靠，新的压测报告给出相反结论，二者不能同时成立",
    },
}


def packet_with(overrides: dict, evidence_claim: str, quote: str = "irrelevant"):
    packet = context.base_packet()
    for key, value in overrides.items():
        if isinstance(value, dict):
            packet[key] = {**packet[key], **value}
        else:
            packet[key] = value
    packet["evidence"][0]["claim"] = evidence_claim
    packet["evidence"][0]["quote"] = quote
    return packet


def english_packet():
    return packet_with(
        EN_PACKET_OVERRIDES,
        "X fails in most deployments",
        "X fails in 62% of deployments.",
    )


def chinese_packet():
    return packet_with(
        ZH_PACKET_OVERRIDES,
        "新的压测报告显示该方案在目标规模下大面积失效",
        "在 62% 的采样部署中，该系统未能在峰值负载下维持稳定输出。",
    )


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cds.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestLanguageDetection(unittest.TestCase):
    """What the packet's own text says about the conversation's language."""

    def test_a_chinese_stance_names_chinese(self):
        self.assertEqual(detect_language(chinese_packet()), "zh")

    def test_an_english_stance_names_english(self):
        self.assertEqual(detect_language(english_packet()), "en")

    def test_an_english_quote_does_not_outvote_a_chinese_stance(self):
        """The case the field-by-field rule exists for.

        A Chinese conversation about an English paper quotes English into the
        packet. Summing characters across fields would let the quotation decide,
        and the card would flip to English on exactly the turn the user most needs
        to read it.
        """
        packet = chinese_packet()
        packet["evidence"][0]["quote"] = (
            "We find that the system fails in 62% of the sampled deployments, "
            "with no meaningful recovery under sustained load."
        )
        packet["evidence"][0]["claim"] = "新论文报告该系统在大规模部署中失败"
        self.assertEqual(detect_language(packet), "zh")

    def test_a_packet_with_no_text_at_all_is_inconclusive(self):
        self.assertIsNone(detect_language({"relation": {"type": "none"}, "evidence": []}))
        self.assertIsNone(detect_language(None))

    def test_a_chinese_sentence_with_english_terms_stays_chinese(self):
        packet = chinese_packet()
        packet["stance"]["claim"] = "该方案在当前规模下是可靠的（见 benchmark_report_v3）"
        self.assertEqual(detect_language(packet), "zh")


class TestLanguageResolution(unittest.TestCase):
    """The order of the three inputs, which is the whole design."""

    def test_auto_follows_the_packet(self):
        config = context.config_with(skill={"language": "auto"})
        self.assertEqual(resolve_language(config, chinese_packet()), "zh")
        self.assertEqual(resolve_language(config, english_packet()), "en")

    def test_an_explicit_override_beats_the_packet(self):
        config = context.config_with(skill={"language": "auto"})
        self.assertEqual(
            resolve_language(config, english_packet(), override="zh"), "zh"
        )

    def test_a_pinned_language_beats_the_packet(self):
        """A study needs the language to be a controlled factor, not a convenience."""
        config = context.config_with(skill={"language": "en"})
        self.assertEqual(resolve_language(config, chinese_packet()), "en")

    def test_the_override_beats_a_pinned_language(self):
        config = context.config_with(skill={"language": "zh"})
        self.assertEqual(resolve_language(config, None, override="en"), "en")

    def test_the_session_hint_is_used_when_the_packet_says_nothing(self):
        config = context.config_with(skill={"language": "auto"})
        self.assertEqual(resolve_language(config, None, session="zh"), "zh")

    def test_the_fallback_is_the_last_resort(self):
        config = context.config_with(skill={"language": "auto", "language_fallback": "en"})
        self.assertEqual(resolve_language(config, None), "en")
        config = context.config_with(skill={"language": "auto", "language_fallback": "zh"})
        self.assertEqual(resolve_language(config, None), "zh")


class TestEnglishCardsArePureEnglish(unittest.TestCase):
    """No Chinese, and no full-width punctuation, in anything rendered as English."""

    def config(self, style: str = "plain"):
        return context.config_with(
            skill={
                "language": "en",
                "mode": "full",
                "interaction": "ambient",
                "profile": "adaptive",
                "numeric_cards": True,
            },
            transparency={"card_style": style},
        )

    def surfaces(self, style: str = "plain"):
        """Every card the engine can render, for one English packet."""
        config = self.config(style)
        packet = english_packet()
        guard = run_guard(packet, config, history={"current_turn": 1, "dismissed": []})
        detection = guard["detection"]
        evaluation = cds._evaluator().build_evaluation(detection, packet, config)
        return {
            "guard card": guard_card(guard, config),
            "detect card": detect_card(detection, config),
            "detect brief": detect_brief(detection, config),
            "evaluation card": evaluation_card(evaluation, config),
            "response card": response_card(evaluation, config),
            "all cards": all_cards(detection, evaluation, config),
            "audit line": audit_line(guard, config),
            "ask payload": repr(ask_payload(guard, config)),
        }

    def test_no_card_in_either_style_contains_chinese(self):
        for style in ("plain", "technical"):
            cards = self.surfaces(style)
            for name, text in cards.items():
                with self.subTest(style=style, card=name):
                    found = CJK_OR_FULLWIDTH.findall(text)
                    self.assertEqual(
                        found,
                        [],
                        f"{name} ({style}) contains CJK/full-width characters: "
                        f"{''.join(sorted(set(found)))}",
                    )

    def test_the_banner_is_english(self):
        card = self.surfaces()["guard card"]
        self.assertTrue(card.startswith("[CDS | detection]"), card.splitlines()[0])

    def test_the_chinese_banner_is_unchanged(self):
        """The fix must not have moved the Chinese rendering."""
        config = context.config_with(skill={"language": "zh"})
        guard = run_guard(chinese_packet(), config, history={"current_turn": 1})
        card = guard_card(guard, config)
        self.assertTrue(card.startswith("【CDS｜检测】"), card.splitlines()[0])
        self.assertIn("观点1（我先前的说法）：「该方案在当前规模下是可靠的」", card)
        self.assertIn("冲突大小", card)

    def test_the_ask_payload_is_english(self):
        payload = ask_payload(
            run_guard(english_packet(), self.config(), history={"current_turn": 1}),
            self.config(),
        )
        self.assertEqual(payload["question"], "Evaluate this?")
        self.assertEqual(
            [option["id"] for option in payload["options"]],
            ["process", "ignore", "later"],
        )
        self.assertEqual(CJK_OR_FULLWIDTH.findall(repr(payload)), [])


class TestReadmeLanguagesStaySeparate(unittest.TestCase):
    """The same bug as the cards, one level up.

    The English README quoted the Chinese card, named the options 处理/忽略/稍后 and
    printed a Chinese audit line, so a reader who does not read Chinese met it in the
    first scroll of the repository page. Both files are checked here rather than left
    to review, because "the English docs have Chinese in them" is exactly the kind of
    drift that looks deliberate once it has been there for a release.
    """

    def test_the_english_readme_contains_no_chinese(self):
        text = (context.REPO_ROOT / "README.md").read_text(encoding="utf-8")
        found = sorted(set(CJK_OR_FULLWIDTH.findall(text)))
        self.assertEqual(
            found,
            [],
            "README.md contains CJK/full-width characters: "
            + "".join(found)
            + " - the English README must be pure English; put the Chinese in "
            "README.zh-CN.md and link to it",
        )

    def test_the_chinese_readme_is_actually_chinese(self):
        text = (context.REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        self.assertGreater(len(CJK_OR_FULLWIDTH.findall(text)), 500)

    def test_each_readme_links_to_the_other(self):
        en = (context.REPO_ROOT / "README.md").read_text(encoding="utf-8")
        zh = (context.REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("](README.zh-CN.md)", en)
        self.assertIn("](README.md)", zh)


class TestCliLanguage(unittest.TestCase):
    """`--lang` and `auto`, end to end."""

    SCREEN = [
        "--type", "evs",
        "--screen", "opp=high,commit=high,vol=high,self=high,spec=high,nov=high",
        "--no-log",
        "--no-turn-advance",
    ]

    def test_an_english_packet_gets_an_english_card_without_any_flag(self):
        """This is the user-facing behaviour: no flag, no config edit."""
        code, out, _ = run_cli(
            "guard", *self.SCREEN,
            "--stance", "X is reliable in this deployment",
            "--anchor", "turn 2: I said X is reliable in this deployment",
            "--evidence", "a new study shows X has major defects",
            "--ask",
        )
        self.assertEqual(code, 0)
        # `--ask` prints the card, the chooser and the audit line. The
        # `CDS_GUARD surface ->` hint belongs to the non-`--ask` rendering, so it is
        # deliberately absent here.
        self.assertIn("[CDS | detection]", out)
        self.assertIn("Evaluate this?", out)
        self.assertIn("CDS recorded", out)
        self.assertEqual(CJK_OR_FULLWIDTH.findall(out), [])

    def test_a_chinese_packet_gets_a_chinese_card_without_any_flag(self):
        code, out, _ = run_cli(
            "guard", *self.SCREEN,
            "--stance", "X 在该场景下是可靠的",
            "--anchor", "第 2 轮我说：X 在该场景下是可靠的",
            "--evidence", "新研究显示 X 在主要使用场景下存在重大缺陷",
            "--ask",
        )
        self.assertEqual(code, 0)
        self.assertIn("【CDS｜检测】", out)
        self.assertIn("是否进入评估？", out)
        self.assertIn("CDS 已记录", out)

    def test_lang_overrides_an_english_packet(self):
        code, out, _ = run_cli(
            "guard", "--lang", "zh", *self.SCREEN,
            "--stance", "X is reliable in this deployment",
            "--anchor", "turn 2: I said X is reliable",
            "--evidence", "a new study shows X has major defects",
            "--ask",
        )
        self.assertEqual(code, 0)
        self.assertIn("【CDS｜检测】", out)

    def test_the_resolved_language_is_recorded(self):
        """The log has to say which language the turn was rendered in."""
        code, out, _ = run_cli(
            "guard", "--json", *self.SCREEN,
            "--stance", "X is reliable in this deployment",
            "--anchor", "turn 2: I said X is reliable",
            "--evidence", "a new study shows X has major defects",
        )
        self.assertEqual(code, 0)
        self.assertIn('"language": "en"', out)
        self.assertIn('"language_source": "packet"', out)


if __name__ == "__main__":
    unittest.main()
