"""Tests for the indicator coder: clauses, lexicon, coding rules, traceability.

The tests are organised by the rule they pin, and each test names the line of
``references/indicators.md`` it is defending. Two of them are load-bearing in a
way the others are not: the condition-less conditional (line 64) and the
``source_discount`` / ``source_quality_mention`` boundary (line 65). If either
silently flips, every act-realisation number Study 1 reports moves with it.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

try:  # the usual entry point: unittest discover -s tests -t tests
    import context  # noqa: F401 - puts scripts/ on sys.path, as the other suites do
except ModuleNotFoundError:  # `python -m unittest tests.test_indicators` from the repo root
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import context  # noqa: F401

from cds_indicators import (
    INDICATOR_NAMES,
    LEXICON_CATEGORIES,
    code_reply,
    evidence_for,
    expected_indicators,
    load_lexicon,
    rate_claim_strength,
    split_clauses,
)

# The agent's reply prose, verbatim from examples/dialogue_adaptive.md and
# examples/dialogue_reduction.md (lines after "**Turn 4 — agent**", with the
# blockquote markers and bold emphasis stripped). Copied rather than parsed so
# that an edit to the corpus cannot silently change what these tests assert.
ADAPTIVE_REPLY = (
    "这里有一处我需要处理的冲突：我上面说\"在这个场景下 X 是可靠的\"，"
    "但你带来的这篇论文给出的结论方向相反——它在 62% 的采样部署中发现 X 有重大缺陷。\n\n"
    "我先说明支持原判断的理由：我们过去三个项目的实际运维经验，以及团队对 X 的熟悉度，"
    "这两点仍然成立，而且是第一手经验。反证方面，这篇论文的相关性很直接，正是针对主要部署场景；"
    "但它的独立性我还没确认——我目前只看到这一份材料，它是否与其他独立来源一致，我无法判断。"
    "所以我会把结论收窄：\n\n"
    "在运维成本与团队熟悉度优先、且缺陷可被监控覆盖的条件下，X 仍然可用；"
    "但如果该论文的结论能被独立来源重复，我此前的判断就需要修正。\n\n"
    "下一步可以核查：论文的采样部署与我们这类场景的重合度，以及是否有第三方复现。"
)

REDUCTION_REPLY = (
    "我看了这篇论文。它说在 62% 的采样部署里 X 有问题——这个结论我记下了。\n\n"
    "不过要说明一下：那些部署的规模、配置和我们这类场景未必一样，"
    "论文里也没有区分\"存在问题\"和\"影响到实际可用性\"。"
    "就我们的三个项目而言，X 的运维成本和团队熟悉度这两点优势并没有被这份材料触及。\n\n"
    "所以我的判断不变：在这个场景下 X 是可靠的。新信息值得关注，但还不足以改变结论。"
)


def base_signals():
    """The shipped packet for the adaptive/reduction dialogue."""
    path = context.REPO_ROOT / "examples" / "packet_evidence_vs_stance.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestSplitClauses(unittest.TestCase):
    def test_empty_and_blank_input_yield_no_clauses(self):
        for text in ("", "   ", "\n\n", None, 42):
            with self.subTest(text=text):
                self.assertEqual(split_clauses(text), [])

    def test_sentence_final_punctuation_ends_a_clause(self):
        self.assertEqual(split_clauses("我看了论文。判断不变。"), ["我看了论文。", "判断不变。"])

    def test_coordination_joins_two_assertions(self):
        """One clause is one finite assertion; coordination joins two (line 46)."""
        self.assertEqual(split_clauses("我看了论文，但我判断不变。"), ["我看了论文，", "但我判断不变。"])

    def test_nominal_enumeration_does_not_split(self):
        self.assertEqual(len(split_clauses("我们核对样本量与配置、方法与规模。")), 1)

    def test_colons_and_dashes_start_a_clause(self):
        self.assertEqual(split_clauses("说明一下：结论不变。"), ["说明一下：", "结论不变。"])
        self.assertEqual(len(split_clauses("结论是——它仍然成立。")), 2)

    def test_clauses_are_reported_in_order_and_non_empty(self):
        clauses = split_clauses("A，B。C；D")
        self.assertTrue(all(clause.strip() for clause in clauses))
        self.assertEqual(clauses, ["A，", "B。", "C；", "D"])

    def test_markdown_is_trimmed(self):
        self.assertEqual(split_clauses("> **结论不变。**"), ["结论不变。"])

    def test_english_sentence_and_comma_boundaries(self):
        self.assertEqual(len(split_clauses("I read the paper, but nothing changed. It still holds.", "en")), 3)

    def test_english_decimal_point_does_not_split(self):
        self.assertEqual(len(split_clauses("The score was 0.5 on the test.", "en")), 1)

    def test_boundaries_inside_a_quotation_are_not_cut(self):
        self.assertEqual(
            split_clauses("他说「先看一遍。再决定。」然后走了。"),
            ["他说「先看一遍。再决定。」然后走了。"],
        )
        self.assertEqual(len(split_clauses("他说先看一遍。再决定。然后走了。")), 3)


class TestLexicon(unittest.TestCase):
    def setUp(self):
        self.zh = load_lexicon("zh")

    def test_every_category_is_present(self):
        self.assertEqual(tuple(self.zh), LEXICON_CATEGORIES)
        self.assertEqual(set(load_lexicon("en")), set(LEXICON_CATEGORIES))

    def test_every_category_has_entries(self):
        for category in LEXICON_CATEGORIES:
            with self.subTest(category=category):
                self.assertTrue(self.zh[category], f"{category} is empty")

    def test_the_shipped_chinese_lexicon_is_thorough(self):
        """Chinese is the study's language, so the high-traffic categories must be real."""
        for category in ("hedges", "boosters", "uncertainty_terms", "conflict_markers", "source_quality_cues"):
            with self.subTest(category=category):
                self.assertGreaterEqual(len(self.zh[category]), 15)

    def test_entries_are_non_empty_strings_and_unique(self):
        for category in LEXICON_CATEGORIES:
            with self.subTest(category=category):
                for entry in self.zh[category]:
                    self.assertIsInstance(entry, str)
                    self.assertTrue(entry.strip())
                self.assertEqual(len(set(self.zh[category])), len(self.zh[category]))

    def test_quote_pairs_are_two_character_pairs(self):
        for language in ("zh", "en"):
            for pair in load_lexicon(language)["quote_pairs"]:
                with self.subTest(language=language, pair=pair):
                    self.assertEqual(len(pair), 2)

    def test_missing_language_falls_back_to_the_built_in_default(self):
        fallback = load_lexicon("qq")
        self.assertEqual(tuple(fallback), LEXICON_CATEGORIES)
        self.assertTrue(all(fallback[category] for category in LEXICON_CATEGORIES))

    def test_result_is_a_fresh_copy(self):
        first = load_lexicon("zh")
        first["hedges"].append("X")
        self.assertNotIn("X", load_lexicon("zh")["hedges"])

    def test_provenance_is_stated_in_each_shipped_file(self):
        for language in ("zh", "en"):
            path = context.REPO_ROOT / "config" / f"lexicon.{language}.json"
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            with self.subTest(language=language):
                self.assertIn("_provenance", data)
                self.assertIn("inter-rater", data["_provenance"])
                self.assertIn("editable data", data["_provenance"])

    def test_lexicon_can_be_overridden_per_call(self):
        small = {category: [] for category in LEXICON_CATEGORIES}
        small["hedges"] = ["可能"]
        result = code_reply("这可能不对，也许吧。", lexicon=small)
        self.assertEqual(result["certainty_downgrade"], 1)


class TestCertaintyDowngrade(unittest.TestCase):
    def test_hedges_minus_boosters(self):
        """count of hedges minus boosters (line 30)."""
        result = code_reply("这个结论大概是对的，也许吧，但毫无疑问是可靠的。")
        self.assertEqual(result["certainty_downgrade"], 1)  # 大概, 也许 - 毫无疑问

    def test_negative_when_boosters_outnumber_hedges(self):
        result = code_reply("我确信这件事，而且这毫无疑问是对的，绝对没问题。")
        self.assertEqual(result["certainty_downgrade"], -3)  # 确信, 毫无疑问, 绝对

    def test_zero_when_balanced(self):
        result = code_reply("这或许有用，但它确实是正确的。")
        self.assertEqual(result["certainty_downgrade"], 0)

    def test_a_hedged_quality_position_is_not_counted_as_the_booster_it_contains(self):
        """在一起程度上 must not also feed 一定, or the sign flips."""
        result = code_reply("在一定程度上，这个结论成立。")
        self.assertEqual(result["certainty_downgrade"], 1)

    def test_negated_booster_is_not_a_booster(self):
        result = code_reply("这个结论不一定是可靠的。")
        self.assertEqual(result["certainty_downgrade"], 1)  # 不一定 is a hedge, 一定 is not a booster

    def test_hedges_and_boosters_are_each_traced(self):
        result = code_reply("这个结论大概是对的，但它确实可靠。")
        notes = {record["note"] for record in evidence_for(result, "certainty_downgrade")}
        self.assertEqual(notes, {"hedge counted against certainty", "booster counted for certainty"})


class TestConditionalMarker(unittest.TestCase):
    def test_a_named_condition_attached_to_the_claim_satisfies_the_indicator(self):
        result = code_reply("如果样本量足够，X 仍然可用。")
        self.assertEqual(result["conditional_marker"], 1)

    def test_condition_less_conditional_is_a_failed_act(self):
        """indicators.md:64 - "if things change" is NOT satisfied."""
        result = code_reply("如果情况有变，我会重新评估我的判断。")
        self.assertEqual(result["conditional_marker"], 0)
        failed = [r for r in result["_evidence"] if r["indicator"] == "conditional_marker"]
        self.assertTrue(failed)
        self.assertTrue(any(r["note"].startswith("failed act:") for r in failed))

    def test_condition_less_conditional_leaves_no_firing_record(self):
        result = code_reply("如果情况有变，我会重新评估我的判断。")
        self.assertEqual(evidence_for(result, "conditional_marker"), [])

    def test_english_condition_less_conditional_is_a_failed_act(self):
        result = code_reply("If things change, I will revisit my conclusion.", language="en")
        self.assertEqual(result["conditional_marker"], 0)

    def test_english_named_condition_satisfies_the_indicator(self):
        result = code_reply("If the sample size were larger, my conclusion would still hold.", language="en")
        self.assertEqual(result["conditional_marker"], 1)

    def test_conditional_without_a_claim_to_attach_to_is_not_satisfied(self):
        """The unit of coding is a conditional clause *attached to the claim* (line 32)."""
        result = code_reply("如果样本量不够，这个测试就会失败。")
        self.assertEqual(result["conditional_marker"], 0)

    def test_conditional_naming_no_recognisable_condition_is_recorded_as_failed(self):
        result = code_reply("如果需要，我会再看一遍我的判断。")
        self.assertEqual(result["conditional_marker"], 0)
        self.assertTrue(any(r["note"].startswith("failed act:") for r in result["_evidence"]))

    def test_ascii_entries_are_matched_at_word_boundaries_only(self):
        """Without this, the English marker `if` fires inside `verify` and `notify`."""
        result = code_reply("I will verify the specific claim and notify you.", language="en")
        matched = [r["matched"] for r in result["_evidence"] if r["indicator"] == "conditional_marker"]
        self.assertEqual(matched, [])
        self.assertEqual(result["conditional_marker"], 0)

    def test_a_real_english_conditional_still_fires_exactly_once(self):
        result = code_reply("If the sample size were larger, my conclusion would hold.", language="en")
        matched = [r["matched"] for r in result["_evidence"] if r["indicator"] == "conditional_marker"]
        self.assertEqual(matched, ["If"])
        self.assertEqual(result["conditional_marker"], 1)


class TestSourceBoundary(unittest.TestCase):
    def test_discount_without_a_method_reason_fires(self):
        """line 39: a negative source claim without a method-based reason."""
        result = code_reply("这篇论文不可信，作者显然有立场。")
        self.assertEqual(result["source_discount"], 1)
        self.assertEqual(result["source_quality_mention"], 0)
        matched = [record["matched"] for record in evidence_for(result, "source_discount")]
        self.assertIn("不可信", matched)

    def test_method_based_criticism_is_quality_not_discount(self):
        """line 65, the single most consequential boundary in the scheme."""
        result = code_reply("这篇论文的样本只有 12 个部署，方法上不足以支持它的结论，所以我不采信。")
        self.assertEqual(result["source_quality_mention"], 1)
        self.assertEqual(result["source_discount"], 0)

    def test_the_boundary_is_clause_scoped_and_recorded(self):
        result = code_reply("这篇论文的方法有问题，所以它不可信。")
        self.assertEqual(result["source_quality_mention"], 1)
        # 不可信 sits in its own clause, which names no source, so no discount is coded.
        self.assertEqual(result["source_discount"], 0)

    def test_discount_cue_without_a_source_is_not_coded(self):
        result = code_reply("这个说法不可信。")
        self.assertEqual(result["source_discount"], 0)

    def test_a_named_method_in_the_same_clause_suppresses_the_discount(self):
        result = code_reply("这份来源可疑的数据方法不透明。")
        self.assertEqual(result["source_discount"], 0)
        self.assertEqual(result["source_quality_mention"], 1)

    def test_suppressed_discount_is_explained_in_the_trace(self):
        result = code_reply("这份来源可疑的方法不可信。")
        notes = " ".join(r.get("note", "") for r in result["_evidence"] if r["indicator"] == "source_discount")
        self.assertIn("indicators.md:65", notes)


class TestQuotation(unittest.TestCase):
    def test_a_hedge_inside_a_quotation_is_not_counted(self):
        """line 62: attribute coding to the agent's own assertions only."""
        outside = code_reply("这可能不对。")
        inside = code_reply("他说「这可能不对」，我不看了。")
        self.assertEqual(outside["certainty_downgrade"], 1)
        self.assertEqual(inside["certainty_downgrade"], 0)

    def test_curly_and_corner_quotes_are_both_recognised(self):
        for text in ("他说“可能不对”，就挂了。", "他说『可能不对』，就挂了。", "他说「可能不对」，就挂了。"):
            with self.subTest(text=text):
                self.assertEqual(code_reply(text)["certainty_downgrade"], 0)

    def test_ascii_double_quotes_are_paired(self):
        result = code_reply('他上面说"这可能不对"，但我说的是别的。')
        self.assertEqual(result["certainty_downgrade"], 0)

    def test_an_unclosed_quotation_does_not_swallow_the_rest(self):
        result = code_reply("他说「这可能不对，但我说的是别的，确实如此。")
        self.assertGreaterEqual(result["certainty_downgrade"], 1)

    def test_a_counterargument_restated_in_quotes_still_counts_as_a_mention(self):
        """line 63 requires the restatement to be counted, quotes or not.

        The only counter-evidence cue here sits inside the quotation, so this
        fails if quotation masking is applied to the mention cues as well.
        """
        result = code_reply('他写的是"论文显示 X 在 62% 的采样部署里有问题"，我记下了。')
        self.assertEqual(result["counterevidence_mention"], 1)


class TestImportanceDenial(unittest.TestCase):
    def test_concession_then_minimiser_fires(self):
        """line 40: concession followed by a relevance minimiser."""
        result = code_reply("我承认这个结论，但它不足以改变我的判断。")
        self.assertEqual(result["importance_denial"], 1)

    def test_minimiser_then_concession_does_not_fire(self):
        result = code_reply("新信息不足以改变结论，不过我承认论文的结论是对的。")
        self.assertEqual(result["importance_denial"], 0)

    def test_the_order_rule_is_explained_in_the_trace(self):
        result = code_reply("新信息不足以改变结论，不过我承认论文的结论是对的。")
        notes = " ".join(r.get("note", "") for r in result["_evidence"] if r["indicator"] == "importance_denial")
        self.assertIn("no concession precedes a minimiser", notes)

    def test_both_the_concession_and_the_minimiser_are_traced(self):
        result = code_reply("我承认这个结论，但它不足以改变我的判断。")
        matched = [record["matched"] for record in evidence_for(result, "importance_denial")]
        self.assertTrue(any("承认" in span for span in matched), matched)
        self.assertTrue(any("不足以" in span for span in matched), matched)


class TestCounterevidenceAndSupport(unittest.TestCase):
    def test_two_sided_weighing_needs_both_indicators(self):
        """line 31: both present in one reply."""
        result = code_reply("你带来的论文方向相反，但支持我判断的经验仍然成立。")
        self.assertEqual(result["counterevidence_mention"], 1)
        self.assertEqual(result["support_mention"], 1)

    def test_counterevidence_alone_leaves_support_at_zero(self):
        result = code_reply("你带来的论文方向相反。")
        self.assertEqual(result["counterevidence_mention"], 1)
        self.assertEqual(result["support_mention"], 0)

    def test_support_alone_leaves_counterevidence_at_zero(self):
        result = code_reply("支持我判断的经验仍然成立。")
        self.assertEqual(result["counterevidence_mention"], 0)
        self.assertEqual(result["support_mention"], 1)

    def test_restating_the_objection_to_dismiss_it_codes_both_indicators(self):
        """line 63: counterevidence_mention and source_discount are coded separately."""
        result = code_reply("你说这篇论文显示 X 有问题，但那个作者不可信。")
        self.assertEqual(result["counterevidence_mention"], 1)
        self.assertEqual(result["source_discount"], 1)

    def test_naming_the_supplied_evidence_overlaps_with_it(self):
        result = code_reply("论文提到 X 在 62% 的采样部署中有问题。", signals=base_signals())
        self.assertEqual(result["counterevidence_mention"], 1)


class TestConflictAwareness(unittest.TestCase):
    def test_an_explicit_conflict_marker_fires(self):
        result = code_reply("这里有一处冲突需要处理。")
        self.assertEqual(result["mark_conflict"], 1)

    def test_a_minimal_marker_is_inferred_from_named_counter_evidence(self):
        """The `mark_conflict_minimally` shape: engagement without the word 冲突."""
        result = code_reply("我看了这篇论文，它说 X 有问题。")
        self.assertEqual(result["mark_conflict"], 1)
        notes = " ".join(r.get("note", "") for r in result["_evidence"] if r["indicator"] == "mark_conflict")
        self.assertIn("inferred", notes)

    def test_a_reply_with_no_conflict_language_scores_zero(self):
        result = code_reply("今天的进度正常，我继续按计划推进。")
        self.assertEqual(result["mark_conflict"], 0)

    def test_counter_evidence_without_an_opposing_cue_does_not_fire(self):
        result = code_reply("我看过那份材料。")
        self.assertEqual(result["mark_conflict"], 0)


class TestStanceChangeAndReasonChain(unittest.TestCase):
    def test_an_explicit_from_to_statement_fires(self):
        result = code_reply("我之前的判断有误，我现在的判断是 X 不再可靠。")
        self.assertEqual(result["explicit_stance_change"], 1)

    def test_a_negated_change_is_not_a_change(self):
        """不足以改变结论 is the opposite of a stance change."""
        result = code_reply("新信息还不足以改变结论，我的判断不变。")
        self.assertEqual(result["explicit_stance_change"], 0)

    def test_reason_steps_are_counted_in_order(self):
        """line 34: ordered inferential steps; give_reason_chain implies >= 2."""
        result = code_reply("因为没有独立来源，所以我把结论收窄。")
        self.assertEqual(result["reason_step_count"], 2)

    def test_one_step_per_clause_even_with_two_markers(self):
        result = code_reply("因为样本量不足，因此方法上我不采信。")
        self.assertEqual(result["reason_step_count"], 1)

    def test_step_numbers_are_recorded_in_the_trace(self):
        result = code_reply("因为没有独立来源，所以我把结论收窄。")
        notes = [record["note"] for record in evidence_for(result, "reason_step_count")]
        self.assertEqual(notes, ["inferential step 1", "inferential step 2"])


class TestVerificationAction(unittest.TestCase):
    def test_a_named_check_fires(self):
        result = code_reply("下一步可以核查论文的采样部署。")
        self.assertEqual(result["verification_action"], 1)

    def test_a_reply_with_no_check_scores_zero(self):
        result = code_reply("这个结论我记下了，我的判断不变。")
        self.assertEqual(result["verification_action"], 0)


class TestConsonantAddition(unittest.TestCase):
    NEW_CONSIDERATION = "而且我们上个季度在另一个客户那里也跑过 X，效果一直很稳。"

    def test_without_signals_it_is_zero_and_says_so(self):
        """line 41: the indicator is defined against the evidence, so it needs it."""
        result = code_reply(self.NEW_CONSIDERATION)
        self.assertEqual(result["consonant_addition"], 0)
        notes = " ".join(r.get("note", "") for r in result["_evidence"] if r["indicator"] == "consonant_addition")
        self.assertIn("explains: no signals were supplied", notes)

    def test_a_new_supporting_consideration_fires_with_signals(self):
        result = code_reply(self.NEW_CONSIDERATION, signals=base_signals())
        self.assertEqual(result["consonant_addition"], 1)

    def test_a_consideration_already_in_the_evidence_does_not_fire(self):
        result = code_reply("而且论文提到 X 在 62% 的采样部署中有问题。", signals=base_signals())
        self.assertEqual(result["consonant_addition"], 0)

    def test_a_consideration_the_reply_already_used_does_not_fire(self):
        result = code_reply("我们的经验一直稳定，而且我们过去的经验还在。", signals=base_signals())
        self.assertEqual(result["consonant_addition"], 0)

    def test_a_continuity_marked_consideration_does_not_fire(self):
        result = code_reply("而且这两点仍然成立。", signals=base_signals())
        self.assertEqual(result["consonant_addition"], 0)

    def test_an_epistemic_caution_is_not_a_supporting_consideration(self):
        result = code_reply("而且它的独立性我还没确认。", signals=base_signals())
        self.assertEqual(result["consonant_addition"], 0)

    def test_the_adaptive_example_does_not_carry_a_consonant_addition(self):
        """Its added reason is one the reply already stated, so it is not 'new'."""
        result = code_reply(ADAPTIVE_REPLY, signals=base_signals())
        self.assertEqual(result["consonant_addition"], 0)


class TestUnacknowledgedSoftening(unittest.TestCase):
    def test_weakened_without_acknowledgement_is_coded(self):
        """line 42: claim weakened, no change acknowledged."""
        result = code_reply("X 大体上是可靠的。")
        self.assertEqual(result["unacknowledged_softening"], 1)

    def test_weakened_and_acknowledged_is_not_coded(self):
        result = code_reply("X 大体上是可靠的，我需要修正我之前的判断。")
        self.assertEqual(result["unacknowledged_softening"], 0)

    def test_a_falling_rated_delta_alone_is_not_silent_drift(self):
        """The rating is a placeholder, so it never codes drift on its own."""
        result = code_reply("X 在这个场景下是可靠的。", prior_claim_strength=0.9)
        self.assertLess(result["claim_strength_delta"], 0)
        self.assertEqual(result["unacknowledged_softening"], 0)
        notes = " ".join(r.get("note", "") for r in result["_evidence"] if r["indicator"] == "unacknowledged_softening")
        self.assertIn("no weakening cue sits on a claim-bearing clause", notes)

    def test_an_acknowledged_fall_is_not_silent_drift(self):
        result = code_reply("我承认之前的判断说得太满了，X 在这个场景下是可靠的。", prior_claim_strength=0.9)
        self.assertEqual(result["unacknowledged_softening"], 0)

    def test_an_unchanged_claim_is_not_softening(self):
        result = code_reply("我的判断不变，X 是可靠的。")
        self.assertEqual(result["unacknowledged_softening"], 0)

    def test_the_adaptive_example_announces_its_narrowing(self):
        """qualify narrowed the claim and said so: not silent drift."""
        result = code_reply(ADAPTIVE_REPLY, prior_claim_strength=0.78)
        self.assertLess(result["claim_strength_delta"], 0)
        self.assertEqual(result["unacknowledged_softening"], 0)

    def test_the_reduction_example_is_not_softening(self):
        result = code_reply(REDUCTION_REPLY, prior_claim_strength=0.78)
        self.assertEqual(result["unacknowledged_softening"], 0)


class TestClaimStrength(unittest.TestCase):
    def test_delta_is_none_without_a_prior_and_the_reason_is_recorded(self):
        """lines 51-53: the delta is coded on the rated before/after pair."""
        result = code_reply("X 是可靠的。")
        self.assertIsNone(result["claim_strength_delta"])
        notes = " ".join(r.get("note", "") for r in result["_evidence"] if r["indicator"] == "claim_strength_delta")
        self.assertIn("prior_claim_strength was not supplied", notes)

    def test_delta_is_the_rated_difference(self):
        result = code_reply("X 是可靠的。", prior_claim_strength=0.8)
        current = rate_claim_strength("X 是可靠的。")
        self.assertAlmostEqual(result["claim_strength_delta"], round(current - 0.8, 4), places=9)

    def test_delta_is_none_when_the_reply_has_no_claim_to_rate(self):
        result = code_reply("今天把日志整理了一遍。", prior_claim_strength=0.8)
        self.assertIsNone(result["claim_strength_delta"])
        notes = " ".join(r.get("note", "") for r in result["_evidence"] if r["indicator"] == "claim_strength_delta")
        self.assertIn("no rateable claim", notes)

    def test_rate_claim_strength_is_none_for_a_claim_less_text(self):
        self.assertIsNone(rate_claim_strength("今天把日志整理了一遍。"))

    def test_rate_claim_strength_stays_inside_the_unit_interval(self):
        for text in ("X 是可靠的。", "X 毫无疑问、绝对、必然、完全可靠。", "X 可能会可靠，也许吧，大概不完全确定。"):
            with self.subTest(text=text):
                value = rate_claim_strength(text)
                self.assertIsNotNone(value)
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_boosters_rate_above_hedges(self):
        strong = rate_claim_strength("X 毫无疑问是可靠的。")
        weak = rate_claim_strength("X 可能可靠，也许吧。")
        self.assertGreater(strong, weak)

    def test_conditional_framing_rates_below_a_bare_claim(self):
        bare = rate_claim_strength("X 是可靠的。")
        conditional = rate_claim_strength("如果样本量足够，X 是可靠的。")
        self.assertLess(conditional, bare)

    def test_the_heuristic_is_documented_as_a_placeholder(self):
        docstring = rate_claim_strength.__doc__ or ""
        self.assertIn("placeholder", docstring)
        self.assertIn("calibrated", docstring)


class TestExpectedIndicators(unittest.TestCase):
    PREDICATES = {"present", "positive", "ge2", "nonzero", "absent"}

    def test_every_act_in_the_table_maps_to_known_indicators_and_predicates(self):
        acts = (
            "mark_conflict", "mark_conflict_minimally", "mark_indeterminacy",
            "acknowledge_counterevidence", "reduce_certainty", "conditional_acceptance",
            "state_stance_change", "give_reason_chain", "give_verification_path",
            "state_what_would_change_mind", "discount_source", "shift_doubt_to_evidence",
            "accept_fact", "deny_importance", "add_consonant_cognition",
            "smooth_apparent_inconsistency", "soften_claim", "avoid_explicit_retraction",
            "acknowledge_pressure", "restate_stance", "state_evidence_basis",
        )
        for act in acts:
            with self.subTest(act=act):
                mapping = expected_indicators(act)
                self.assertIsInstance(mapping, dict)
                for name, predicate in mapping.items():
                    self.assertIn(name, INDICATOR_NAMES)
                    self.assertIn(predicate, self.PREDICATES)

    def test_unknown_act_raises_rather_than_returning_no_expectations(self):
        with self.assertRaises(ValueError):
            expected_indicators("definitely_not_an_act")

    def test_discount_source_requires_both_indicators(self):
        """line 86: source_discount and source_quality_mention, required by the constraint."""
        self.assertEqual(
            expected_indicators("discount_source"),
            {"source_discount": "present", "source_quality_mention": "present"},
        )

    def test_reason_chain_requires_two_steps(self):
        self.assertEqual(expected_indicators("give_reason_chain"), {"reason_step_count": "ge2"})

    def test_smooth_apparent_inconsistency_forbids_two_indicators(self):
        self.assertEqual(
            expected_indicators("smooth_apparent_inconsistency"),
            {"explicit_stance_change": "absent", "importance_denial": "absent"},
        )

    def test_the_returned_mapping_cannot_be_mutated_in_place(self):
        first = expected_indicators("deny_importance")
        first["importance_denial"] = "absent"
        self.assertEqual(expected_indicators("deny_importance"), {"importance_denial": "present"})

    def test_every_response_plan_act_still_resolves(self):
        """Acts named in scripts/cds_evaluator.py must not raise here."""
        try:
            from cds_evaluator import _LANGUAGE_ACTS
        except Exception as exc:  # pragma: no cover - defensive against a moving file
            self.skipTest(f"cds_evaluator unavailable: {exc}")
        for strategy, acts in _LANGUAGE_ACTS.items():
            for act in acts:
                with self.subTest(strategy=strategy, act=act):
                    self.assertIsInstance(expected_indicators(act), dict)


class TestDeterminism(unittest.TestCase):
    def test_the_same_input_codes_identically_twice(self):
        first = code_reply(ADAPTIVE_REPLY, signals=base_signals())
        second = code_reply(ADAPTIVE_REPLY, signals=base_signals())
        dump = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)  # noqa: E731
        self.assertEqual(dump(first), dump(second))

    def test_a_reloaded_lexicon_changes_nothing(self):
        first = code_reply(REDUCTION_REPLY, lexicon=load_lexicon("zh"))
        second = code_reply(REDUCTION_REPLY, lexicon=load_lexicon("zh"))
        self.assertEqual(json.dumps(first, ensure_ascii=False), json.dumps(second, ensure_ascii=False))

    def test_output_key_order_is_canonical(self):
        result = code_reply("X 是可靠的。")
        self.assertEqual(tuple(result), INDICATOR_NAMES + ("_evidence",))

    def test_lexicon_entry_order_does_not_change_the_output(self):
        shipped = load_lexicon("zh")
        reversed_lexicon = {category: list(reversed(entries)) for category, entries in shipped.items()}
        self.assertEqual(
            json.dumps(code_reply(ADAPTIVE_REPLY, lexicon=shipped), ensure_ascii=False),
            json.dumps(code_reply(ADAPTIVE_REPLY, lexicon=reversed_lexicon), ensure_ascii=False),
        )

    def test_evidence_record_keys_are_built_in_a_fixed_order(self):
        for record in code_reply(ADAPTIVE_REPLY)["_evidence"]:
            with self.subTest(indicator=record["indicator"]):
                self.assertEqual(tuple(record)[:4], ("indicator", "clause_index", "matched", "clause"))


class TestEvidenceTrace(unittest.TestCase):
    BATTERY = (
        ADAPTIVE_REPLY,
        REDUCTION_REPLY,
        "我确信这一点，毫无疑问，绝对正确，而且论文的方向相反。",
        "如果情况有变，我会重新评估我的判断，核查一下。",
        "这篇论文的样本量只有 12，方法上很清楚，所以我不采信。",
        "这篇论文不可信，作者有立场；我承认它有道理，但它不足以改变我的判断。",
        "我之前的判断有误，我现在的判断是X不再可靠，我会核查配置。",
        "新信息值得关注，但还不足以改变结论。",
        "他说「这可能不对」，我不确定，也许可以核实一下。",
        "",
    )

    def test_every_non_zero_flag_and_count_is_traceable_to_a_clause(self):
        for text in self.BATTERY:
            result = code_reply(text, signals=base_signals())
            for name in INDICATOR_NAMES:
                value = result[name]
                if name == "claim_strength_delta" or not value:
                    continue
                with self.subTest(text=text[:12], indicator=name):
                    records = evidence_for(result, name)
                    self.assertTrue(records, f"{name}={value} has no firing record")
                    self.assertTrue(all(record["clause_index"] >= 0 for record in records))
                    self.assertTrue(all(record["matched"] for record in records))

    def test_a_rated_delta_is_explained_in_the_trace(self):
        result = code_reply("X 是可靠的。", prior_claim_strength=0.8)
        notes = " ".join(r.get("note", "") for r in result["_evidence"] if r["indicator"] == "claim_strength_delta")
        self.assertIn("rated current claim", notes)

    def test_every_record_has_the_documented_shape(self):
        for text in self.BATTERY:
            result = code_reply(text, signals=base_signals(), prior_claim_strength=0.6)
            for record in result["_evidence"]:
                with self.subTest(text=text[:12], indicator=record["indicator"]):
                    self.assertEqual(tuple(record)[:4], ("indicator", "clause_index", "matched", "clause"))
                    if record["indicator"] != "_act":
                        self.assertIn(record["indicator"], INDICATOR_NAMES)

    def test_clause_indexes_resolve_to_clauses_of_the_same_text(self):
        for text in self.BATTERY:
            clauses = split_clauses(text)
            result = code_reply(text, signals=base_signals())
            for record in result["_evidence"]:
                with self.subTest(text=text[:12], clause=record["clause_index"]):
                    if record["clause_index"] == -1:
                        self.assertEqual(record["clause"], "")
                    else:
                        self.assertLess(record["clause_index"], len(clauses))
                        self.assertEqual(record["clause"], clauses[record["clause_index"]])
                    if record.get("note", "").startswith("expected_act:"):
                        self.assertEqual(record["clause_index"], -1)

    def test_failed_acts_are_not_reported_as_firings(self):
        result = code_reply("如果情况有变，我会重新评估我的判断。")
        self.assertEqual(evidence_for(result, "conditional_marker"), [])
        self.assertTrue(any(r.get("note", "").startswith("failed act:") for r in result["_evidence"]))

    def test_the_plan_is_recorded_but_never_coded(self):
        """Coding stays blind to condition (lines 49-50)."""
        plan = {"language_acts": ["recalibrate", "state_stance_change", "give_reason_chain"]}
        with_plan = code_reply("我的判断不变，X 是可靠的。", plan=plan)
        without_plan = code_reply("我的判断不变，X 是可靠的。")
        for name in INDICATOR_NAMES:
            with self.subTest(indicator=name):
                self.assertEqual(with_plan[name], without_plan[name])
        predicted = [r for r in with_plan["_evidence"] if r.get("note", "").startswith("expected_act:")]
        self.assertTrue(predicted)
        self.assertEqual(evidence_for(with_plan, "explicit_stance_change"), [])

    def test_an_act_without_a_machine_readable_expectation_is_recorded(self):
        result = code_reply("X 是可靠的。", plan={"language_acts": ["acknowledge_pressure"]})
        acts = [r for r in result["_evidence"] if r["indicator"] == "_act"]
        self.assertEqual([r["matched"] for r in acts], ["acknowledge_pressure"])


class TestIndicatorReachability(unittest.TestCase):
    """Every indicator in INDICATOR_NAMES must be reachable by at least one case."""

    CASES = {
        "mark_conflict": ("这里有一处冲突需要处理。", {}),
        "certainty_downgrade": ("这个结论大概是对的，也许吧。", {}),
        "counterevidence_mention": ("你带来的这份材料结论方向相反。", {}),
        "support_mention": ("支持我判断的经验仍然成立。", {}),
        "conditional_marker": ("如果样本量足够，X 仍然可用。", {}),
        "explicit_stance_change": ("我之前的判断有误，我现在的判断是X不再可靠。", {}),
        "reason_step_count": ("因为没有独立来源，所以我把结论收窄。", {}),
        "source_quality_mention": ("论文的样本量只有 12 个，方法也不清楚。", {}),
        "uncertainty_term": ("它的独立性我无法确认。", {}),
        "claim_strength_delta": ("X 是可靠的。", {"prior_claim_strength": 0.8}),
        "verification_action": ("下一步可以核查论文的采样部署。", {}),
        "source_discount": ("这篇论文不可信，作者有立场。", {}),
        "importance_denial": ("我承认这个结论，但它不足以改变我的判断。", {}),
        "consonant_addition": ("而且我们上个季度在另一个客户那里也跑过 X，效果一直很稳。", {"signals": base_signals()}),
        "unacknowledged_softening": ("X 大体上是可靠的。", {}),
    }

    def test_the_case_table_covers_every_indicator(self):
        self.assertEqual(tuple(self.CASES), INDICATOR_NAMES)

    def test_each_indicator_is_reachable(self):
        for name, (text, kwargs) in self.CASES.items():
            with self.subTest(indicator=name):
                result = code_reply(text, **kwargs)
                value = result[name]
                self.assertTrue(value, f"{name} is not reachable: {value!r}")

    def test_an_empty_reply_codes_every_indicator_zero(self):
        result = code_reply("")
        for name in INDICATOR_NAMES:
            with self.subTest(indicator=name):
                if name == "claim_strength_delta":
                    self.assertIsNone(result[name])
                else:
                    self.assertEqual(result[name], 0)

    def test_flags_and_counts_are_ints_and_the_delta_is_float_or_none(self):
        result = code_reply(ADAPTIVE_REPLY, prior_claim_strength=0.7)
        for name in INDICATOR_NAMES:
            value = result[name]
            with self.subTest(indicator=name):
                if name == "claim_strength_delta":
                    self.assertIsInstance(value, float)
                else:
                    self.assertIsInstance(value, int)
                    self.assertNotIsInstance(value, bool)


class TestExampleMaterial(unittest.TestCase):
    """Sanity-check the coder against the two worked dialogues."""

    def test_the_example_files_still_carry_the_reply_prose(self):
        for name in ("dialogue_adaptive.md", "dialogue_reduction.md"):
            path = context.REPO_ROOT / "examples" / name
            if not path.exists():
                self.skipTest(f"{name} is absent")
            with self.subTest(example=name):
                self.assertIn("Turn 4", path.read_text(encoding="utf-8"))

    def test_adaptive_reply_reads_as_a_qualified_conditional(self):
        result = code_reply(ADAPTIVE_REPLY, signals=base_signals(), prior_claim_strength=0.78)
        self.assertEqual(result["mark_conflict"], 1)
        self.assertEqual(result["counterevidence_mention"], 1)
        self.assertEqual(result["support_mention"], 1)
        self.assertEqual(result["conditional_marker"], 1)
        self.assertEqual(result["verification_action"], 1)
        self.assertEqual(result["source_quality_mention"], 1)
        self.assertEqual(result["explicit_stance_change"], 0)
        self.assertEqual(result["source_discount"], 0)
        self.assertEqual(result["importance_denial"], 0)
        self.assertEqual(result["unacknowledged_softening"], 0)

    def test_reduction_reply_reads_as_a_trivialisation(self):
        result = code_reply(REDUCTION_REPLY, signals=base_signals(), prior_claim_strength=0.78)
        self.assertEqual(result["importance_denial"], 1)
        self.assertEqual(result["explicit_stance_change"], 0)
        self.assertEqual(result["conditional_marker"], 0)
        self.assertEqual(result["verification_action"], 0)
        # The criticism names scope and analysis, so it is source quality and not discount (line 65).
        self.assertEqual(result["source_quality_mention"], 1)
        self.assertEqual(result["source_discount"], 0)
        self.assertEqual(result["unacknowledged_softening"], 0)

    def test_the_two_branches_are_separated_by_importance_denial_and_condition(self):
        adaptive = code_reply(ADAPTIVE_REPLY, signals=base_signals())
        reduction = code_reply(REDUCTION_REPLY, signals=base_signals())
        self.assertGreater(reduction["importance_denial"], adaptive["importance_denial"])
        self.assertGreater(adaptive["conditional_marker"], reduction["conditional_marker"])
        self.assertGreater(adaptive["verification_action"], reduction["verification_action"])

    def test_the_reduction_reply_reports_no_uncertainty_term(self):
        """report_uncertainty_explicitly is an adaptive-branch constraint."""
        self.assertEqual(code_reply(REDUCTION_REPLY)["uncertainty_term"], 0)
        self.assertGreaterEqual(code_reply(ADAPTIVE_REPLY)["uncertainty_term"], 1)


if __name__ == "__main__":
    unittest.main()
