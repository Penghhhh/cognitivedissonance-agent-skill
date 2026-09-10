"""Tests for the response scorer: act realisation, constraint checks, arithmetic."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import context

from score_responses import (
    _quoted_spans,
    _realised,
    check_constraints,
    read_log,
    read_pairs,
    render,
    score_pair,
    summarise,
)


def plan(**overrides):
    base = {
        "strategy": "qualify",
        "branch": "adaptive",
        "acts_withheld": False,
        "language_acts": ["mark_conflict", "reduce_certainty"],
        "stance_update": {"from": "旧立场", "to": "条件化表述", "planned_change": True},
        "constraints": ["no_fabrication", "no_hidden_chain_of_thought", "report_uncertainty_explicitly"],
    }
    base.update(overrides)
    return base


def evaluation(plan_dict):
    return {"response_plan": plan_dict, "evaluation_result": {"recommended_strategy": plan_dict["strategy"]}}


def pair(reply_text, plan_dict=None, signals=None, pair_id="p1"):
    doc = {"pair_id": pair_id, "reply_text": reply_text, "evaluation": evaluation(plan_dict or plan())}
    if signals is not None:
        doc["signals"] = signals
    return doc


class TestPredicates(unittest.TestCase):
    def test_present(self):
        self.assertTrue(_realised("present", 1))
        self.assertFalse(_realised("present", 0))

    def test_positive(self):
        self.assertTrue(_realised("positive", 2))
        self.assertFalse(_realised("positive", 0))
        self.assertFalse(_realised("positive", -1))

    def test_nonzero_allows_negative(self):
        self.assertTrue(_realised("nonzero", -0.4))
        self.assertFalse(_realised("nonzero", 0.0))

    def test_ge2(self):
        self.assertTrue(_realised("ge2", 2))
        self.assertFalse(_realised("ge2", 1))

    def test_absent(self):
        self.assertTrue(_realised("absent", 0))
        self.assertFalse(_realised("absent", 1))

    def test_unknown_predicate_is_not_realised(self):
        self.assertFalse(_realised("something-else", 1))


class TestQuotedSpans(unittest.TestCase):
    def test_chinese_corner_brackets(self):
        self.assertEqual(_quoted_spans("他说「结论不成立」而已"), ["结论不成立"])

    def test_curly_quotes(self):
        self.assertEqual(_quoted_spans("原文是“报告未给出方法”一句"), ["报告未给出方法"])

    def test_multiple_spans(self):
        self.assertEqual(len(_quoted_spans("「一」和「二」")), 2)

    def test_unterminated_quote_yields_nothing(self):
        self.assertEqual(_quoted_spans("「没有闭合"), [])

    def test_no_quotes(self):
        self.assertEqual(_quoted_spans("普通句子"), [])


class TestConstraintChecks(unittest.TestCase):
    def codes(self, *wanted):
        return list(wanted)

    def test_a_code_absent_from_the_plan_is_not_reported(self):
        results = check_constraints({"uncertainty_term": 0}, plan(constraints=[]), None, "")
        self.assertEqual(results, [])

    def test_report_uncertainty_passes_on_one_term(self):
        results = check_constraints(
            {"uncertainty_term": 1}, plan(), None, ""
        )
        row = next(r for r in results if r["code"] == "report_uncertainty_explicitly")
        self.assertEqual(row["status"], "pass")

    def test_report_uncertainty_fails_on_zero(self):
        results = check_constraints({"uncertainty_term": 0}, plan(), None, "")
        row = next(r for r in results if r["code"] == "report_uncertainty_explicitly")
        self.assertEqual(row["status"], "fail")

    def test_no_fabrication_is_not_checked_without_context(self):
        """The packet is not the conversation, so it cannot resolve a quotation.

        An earlier version compared quotes against the packet's one-line stance
        claim and flagged an agent paraphrasing its own prior position as a
        fabrication — a false positive on the constraint that exists to catch
        invented sources.
        """
        results = check_constraints({}, plan(), None, "「某段引文」")
        row = next(r for r in results if r["code"] == "no_fabrication")
        self.assertEqual(row["status"], "not_checked")

    def test_no_fabrication_passes_when_quotes_resolve(self):
        ctx = "用户带来一份报告，原文是「乙结论的原话」，与既有判断相反。"
        results = check_constraints({}, plan(), ctx, "原文是「乙结论的原话」，所以我修正。")
        row = next(r for r in results if r["code"] == "no_fabrication")
        self.assertEqual(row["status"], "pass")

    def test_no_fabrication_fails_on_an_invented_quote(self):
        ctx = "用户带来一份报告，原文是「乙结论的原话」，与既有判断相反。"
        results = check_constraints({}, plan(), ctx, "原文是「完全不同的一段话」，所以我修正。")
        row = next(r for r in results if r["code"] == "no_fabrication")
        self.assertEqual(row["status"], "fail")

    def test_no_fabrication_fails_on_an_invented_url(self):
        results = check_constraints(
            {}, plan(), "用户提到一份报告。", "参见 https://example.invalid/paper 的方法部分。"
        )
        row = next(r for r in results if r["code"] == "no_fabrication")
        self.assertEqual(row["status"], "fail")

    def test_no_fabrication_passes_when_the_url_is_in_the_context(self):
        ctx = "用户发来 https://example.org/paper 这份报告。"
        results = check_constraints({}, plan(), ctx, "参见 https://example.org/paper 的方法部分。")
        row = next(r for r in results if r["code"] == "no_fabrication")
        self.assertEqual(row["status"], "pass")

    def test_hidden_chain_of_thought_is_detected_in_english(self):
        results = check_constraints({}, plan(), None, "Let me think step by step about this.")
        row = next(r for r in results if r["code"] == "no_hidden_chain_of_thought")
        self.assertEqual(row["status"], "fail")

    def test_hidden_chain_of_thought_is_detected_in_chinese(self):
        results = check_constraints({}, plan(), None, "我先想一想这个问题。")
        row = next(r for r in results if r["code"] == "no_hidden_chain_of_thought")
        self.assertEqual(row["status"], "fail")

    def test_clean_reply_passes_the_reasoning_check(self):
        results = check_constraints({}, plan(), None, "现有证据不足以支持原结论。")
        row = next(r for r in results if r["code"] == "no_hidden_chain_of_thought")
        self.assertEqual(row["status"], "pass")

    def test_discount_without_a_reason_fails(self):
        codes = self.codes("discount_requires_checkable_reason")
        results = check_constraints(
            {"source_discount": 1, "source_quality_mention": 0}, plan(constraints=codes), None, ""
        )
        self.assertEqual(results[0]["status"], "fail")

    def test_discount_with_a_reason_passes(self):
        codes = self.codes("discount_requires_checkable_reason")
        results = check_constraints(
            {"source_discount": 1, "source_quality_mention": 1}, plan(constraints=codes), None, ""
        )
        self.assertEqual(results[0]["status"], "pass")

    def test_no_discount_passes_vacuously(self):
        codes = self.codes("discount_requires_checkable_reason")
        results = check_constraints({"source_discount": 0}, plan(constraints=codes), None, "")
        self.assertEqual(results[0]["status"], "pass")

    def test_silent_retraction_fails_when_unacknowledged(self):
        codes = self.codes("no_silent_retraction")
        coding = {"claim_strength_delta": -0.3, "explicit_stance_change": 0, "certainty_downgrade": 0}
        results = check_constraints(coding, plan(constraints=codes), None, "")
        self.assertEqual(results[0]["status"], "fail")

    def test_silent_retraction_passes_when_hedged(self):
        codes = self.codes("no_silent_retraction")
        coding = {"claim_strength_delta": -0.3, "explicit_stance_change": 0, "certainty_downgrade": 1}
        results = check_constraints(coding, plan(constraints=codes), None, "")
        self.assertEqual(results[0]["status"], "pass")

    def test_silent_retraction_is_not_checked_without_a_delta(self):
        codes = self.codes("no_silent_retraction")
        results = check_constraints({"claim_strength_delta": None}, plan(constraints=codes), None, "")
        self.assertEqual(results[0]["status"], "not_checked")

    def test_pressure_disclosure_passes_when_referenced(self):
        codes = self.codes("disclose_pressure_driver")
        results = check_constraints({}, plan(constraints=codes), None, "你一直要求我改口，但证据不足。")
        self.assertEqual(results[0]["status"], "pass")

    def test_pressure_disclosure_fails_when_silent(self):
        codes = self.codes("disclose_pressure_driver")
        results = check_constraints({}, plan(constraints=codes), None, "证据不足，维持原判断。")
        self.assertEqual(results[0]["status"], "fail")

    def test_fidelity_is_never_passed_from_reply_text(self):
        codes = self.codes("fidelity_not_advice")
        results = check_constraints({}, plan(constraints=codes), None, "这是仿真，不是建议。")
        self.assertEqual(results[0]["status"], "not_checked")

    def test_withhold_acts_runs_no_checks_at_all(self):
        codes = self.codes("report_uncertainty_explicitly", "no_fabrication")
        results = check_constraints({}, plan(constraints=codes, acts_withheld=True), None, "")
        self.assertEqual(results, [])


class TestScorePair(unittest.TestCase):
    def test_an_act_with_no_expectation_is_marked_unchecked(self):
        # `withhold_conclusion` appears in plans but not in the act table.
        p = plan(language_acts=["withhold_conclusion"])
        row = score_pair(pair("暂不下结论。", p), context.BASE_CONFIG)
        self.assertFalse(row["acts"][0]["checked"])

    def test_a_realised_act_is_counted(self):
        p = plan(language_acts=["reduce_certainty"])
        row = score_pair(pair("这一结论可能并不成立。", p), context.BASE_CONFIG)
        self.assertTrue(row["acts"][0]["checked"])
        self.assertTrue(row["acts"][0]["realised"])

    def test_an_unrealised_act_is_counted_as_a_failure(self):
        p = plan(language_acts=["state_stance_change"])
        row = score_pair(pair("结论保持不变。", p), context.BASE_CONFIG)
        self.assertTrue(row["acts"][0]["checked"])
        self.assertFalse(row["acts"][0]["realised"])

    def test_evidence_trace_is_not_leaked_into_the_indicators(self):
        row = score_pair(pair("这一结论可能不成立。"), context.BASE_CONFIG)
        self.assertNotIn("_evidence", row["indicators"])

    def test_agreement_is_true_when_observed_matches_the_plan(self):
        p = plan(language_acts=["state_stance_change"])
        row = score_pair(pair("我改变了判断：新证据不支持原结论。", p), context.BASE_CONFIG)
        self.assertTrue(row["planned_change"])
        self.assertTrue(row["observed_change"])
        self.assertTrue(row["agrees"])

    def test_agreement_is_false_when_the_plan_moved_and_the_reply_did_not(self):
        p = plan(language_acts=[], stance_update={"from": "甲", "to": "乙", "planned_change": True})
        row = score_pair(pair("结论不变。", p), context.BASE_CONFIG)
        self.assertFalse(row["agrees"])

    def test_determinism(self):
        p = plan(language_acts=["mark_conflict", "reduce_certainty"])
        text = "新证据与既有立场相冲突，因此我的判断可能需要调整。"
        first = score_pair(pair(text, p), context.BASE_CONFIG)
        second = score_pair(pair(text, p), context.BASE_CONFIG)
        self.assertEqual(first["indicators"], second["indicators"])
        self.assertEqual(first["violations"], second["violations"])


class TestSummarise(unittest.TestCase):
    def test_counts_and_rates(self):
        p = plan(language_acts=["reduce_certainty"])
        rows = [
            score_pair(pair("可能并不成立。", p, pair_id="a"), context.BASE_CONFIG),
            score_pair(pair("结论确定成立。", p, pair_id="b"), context.BASE_CONFIG),
        ]
        summary = summarise(rows)
        self.assertEqual(summary["replies"], 2)
        self.assertEqual(summary["act_expected"]["reduce_certainty"], 2)
        self.assertEqual(summary["act_realised"]["reduce_certainty"], 1)

    def test_unchecked_acts_are_excluded_from_the_rate(self):
        p = plan(language_acts=["withhold_conclusion"])
        summary = summarise([score_pair(pair("暂不下结论。", p), context.BASE_CONFIG)])
        self.assertEqual(summary["act_expected"], {})
        self.assertEqual(summary["act_unchecked"]["withhold_conclusion"], 1)

    def test_violations_are_tallied_by_status(self):
        p = plan(constraints=["report_uncertainty_explicitly"], language_acts=[])
        summary = summarise([score_pair(pair("结论确定。", p), context.BASE_CONFIG)])
        self.assertEqual(summary["violations"]["report_uncertainty_explicitly"]["fail"], 1)

    def test_empty_input_has_no_agreement_rate(self):
        summary = summarise([])
        self.assertIsNone(summary["agreement_rate"])
        self.assertEqual(summary["replies"], 0)


class TestRender(unittest.TestCase):
    def test_report_carries_the_required_caveat(self):
        text = render(summarise([]), [])
        self.assertIn("cannot show", text)

    def test_report_renders_the_no_data_case(self):
        text = render(summarise([]), [])
        self.assertIn("_none_", text)

    def test_render_is_deterministic(self):
        p = plan(language_acts=["reduce_certainty"])
        rows = [score_pair(pair("可能并不成立。", p), context.BASE_CONFIG)]
        self.assertEqual(render(summarise(rows), rows), render(summarise(rows), rows))


class TestReaders(unittest.TestCase):
    def test_read_pairs_defaults_the_id_to_the_stem(self):
        with context.scratch_dir() as tmp:
            path = Path(tmp) / "alpha.json"
            path.write_text(json.dumps({"reply_text": "x", "evaluation": evaluation(plan())}), encoding="utf-8")
            pairs = read_pairs(Path(tmp))
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["pair_id"], "alpha")

    def test_read_log_skips_replies_that_were_not_stored(self):
        with context.scratch_dir() as tmp:
            path = Path(tmp) / "log.jsonl"
            lines = [
                {"stage": "detect", "payload": {}},
                {"stage": "respond", "payload": {"reply": {"supplied": True, "text": "回复正文"}, "strategy": "qualify"}},
                {"stage": "respond", "payload": {"reply": {"supplied": False}}},
            ]
            path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
            pairs = read_log(path)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["reply_text"], "回复正文")

    def test_read_log_tolerates_blank_lines(self):
        with context.scratch_dir() as tmp:
            path = Path(tmp) / "log.jsonl"
            body = json.dumps({"stage": "respond", "payload": {"reply": {"text": "x"}}})
            path.write_text(f"\n{body}\n\n", encoding="utf-8")
            self.assertEqual(len(read_log(path)), 1)


if __name__ == "__main__":
    unittest.main()
