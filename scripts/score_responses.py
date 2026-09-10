#!/usr/bin/env python3
"""Act-realisation and constraint-violation rates over produced replies.

What this measures, and why it is the number Study 1 needs
----------------------------------------------------------
``references/indicators.md`` states the design in one line: a response plan's
``language_acts`` are a **prediction**, the coded indicators are the
**observation**, and agreement between the two is a result. Without this harness the
repository can only report what the engine decided, which is the engine grading
itself.

Two numbers come out of each reply, and they measure different things:

* **Act realisation** — of the acts the plan asked for, how many did the reply
  actually realise? A ``qualify`` whose reply never names a condition is a
  compliance failure, and it is invisible if only present indicators are counted.
* **Constraint violation** — did the reply stay inside the hard limits? These are
  independent of strategy, and a violation is a hard failure rather than a
  behavioural observation.

Report them separately. Pooling them would let a reply that followed the plan
perfectly but fabricated a citation read the same as one that quietly ignored the
plan.

What this cannot show
---------------------
It cannot say whether the plan asked for the right thing — only whether the reply
did what the plan said. It also inherits the coder's limits: the lexicons are
project-authored and unvalidated, and ``claim_strength_delta`` rests on an explicit
placeholder. Every rate below is therefore an **agreement between two unvalidated
instruments**, and the inter-rater protocol in ``references/codebook.md`` is what
would put a number on that.

Input
-----
A directory of ``*.json`` pairs::

    {
      "pair_id": "s35_run1",
      "reply_text": "...",              # the reply the host model produced
      "evaluation": { ... }             # an evaluation record from `cds.py evaluate`
    }

``signals`` may be included so that ``consonant_addition`` is decidable; without it
that indicator is reported as not checked rather than as zero. A JSONL log can be
read instead with ``--log``, but only if it was written with
``logging.include_reply: true`` — the reply is not stored by default, because it is
participant text.

Usage::

    python scripts/score_responses.py --pairs pairs/ --write-report
    python scripts/score_responses.py --log logs/cds_skill.jsonl --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cds_config import REPO_ROOT, load_config, write_text  # noqa: E402
from cds_indicators import INDICATOR_NAMES, code_reply, expected_indicators  # noqa: E402

REPORT_PATH = REPO_ROOT / "eval" / "responses.md"

#: Cues for the one constraint that has no coded indicator behind it. The scheme
#: maps the `acknowledge_pressure` act to "explicit mention of the user's
#: insistence" but defines no variable for it, so the check needs its own list.
#: Project-authored and unvalidated, like the main lexicons; it belongs in
#: `config/lexicon.<lang>.json` once someone owns calibrating it.
PRESSURE_CUES = (
    "你一直", "你坚持", "你反复", "你要求我", "按你的意思", "顺着你", "既然你坚持",
    "压力", "你希望我改口", "你的坚持",
    "you keep", "you insist", "you have repeatedly", "as you demand", "pressure",
    "since you insist", "you want me to change",
)

#: Phrases that indicate the model narrated its own reasoning rather than giving
#: auditable key points. Deliberately narrow: this is a hard-failure check, and a
#: false positive here accuses a compliant reply.
REASONING_TRACE_CUES = (
    "let me think step by step", "let's think step by step", "my chain of thought",
    "thinking step by step", "让我一步步思考", "我的推理过程是", "我先想一想", "内心推理",
)


def read_pairs(directory: Path) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.setdefault("pair_id", path.stem)
        pairs.append(doc)
    return pairs


def read_log(path: Path) -> list[dict[str, Any]]:
    """Pull reply-bearing respond records out of a JSONL log."""
    pairs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record.get("stage") != "respond":
            continue
        payload = record.get("payload") or {}
        reply = payload.get("reply") or {}
        text = reply.get("text")
        if not text:
            continue
        pairs.append(
            {
                "pair_id": record.get("record_id") or f"{record.get('run_id')}_{record.get('turn_id')}",
                "reply_text": text,
                "evaluation": payload,
                "signals": record.get("signals"),
            }
        )
    return pairs


def _realised(predicate: str, value: Any) -> bool:
    if predicate == "present":
        return bool(value)
    if predicate == "positive":
        return isinstance(value, (int, float)) and value > 0
    if predicate == "nonzero":
        return isinstance(value, (int, float)) and abs(value) > 1e-9
    if predicate == "ge2":
        return isinstance(value, (int, float)) and value >= 2
    if predicate == "absent":
        return not value
    return False


def score_pair(
    pair: dict[str, Any], config: dict[str, Any], context_text: str | None = None
) -> dict[str, Any]:
    """Code one reply and compare it against the plan it was answering."""
    plan = (pair.get("evaluation") or {}).get("response_plan") or {}
    signals = pair.get("signals")
    language = config["skill"]["language"]

    coding = code_reply(
        pair.get("reply_text") or "",
        signals=signals,
        plan=plan,
        language=language,
        prior_claim_strength=((signals or {}).get("stance") or {}).get("confidence"),
    )
    coding.pop("_evidence", None)

    acts = plan.get("language_acts") or []
    act_rows: list[dict[str, Any]] = []
    for act in acts:
        expectations = expected_indicators(act)
        checks = {name: _realised(pred, coding.get(name)) for name, pred in expectations.items()}
        realised = bool(checks) and all(checks.values())
        act_rows.append(
            {
                "act": act,
                "realised": realised,
                "checks": checks,
                # No machine-readable expectation for this act: recorded rather than
                # silently counted as a failure.
                "checked": bool(checks),
            }
        )

    violations = check_constraints(coding, plan, context_text, pair.get("reply_text") or "")

    planned_change = (plan.get("stance_update") or {}).get("planned_change")
    observed_change = bool(coding.get("explicit_stance_change")) or bool(
        coding.get("unacknowledged_softening")
    ) or (isinstance(coding.get("claim_strength_delta"), (int, float)) and abs(coding["claim_strength_delta"]) > 1e-9)

    return {
        "pair_id": pair.get("pair_id"),
        "strategy": plan.get("strategy"),
        "branch": plan.get("branch"),
        "acts_withheld": bool(plan.get("acts_withheld")),
        "acts": act_rows,
        "violations": violations,
        "indicators": coding,
        "planned_change": planned_change,
        "observed_change": observed_change,
        "agrees": (planned_change is None) or (bool(planned_change) == observed_change),
    }


def check_constraints(
    coding: dict[str, Any],
    plan: dict[str, Any],
    context_text: str | None,
    reply_text: str,
) -> list[dict[str, str]]:
    """Evaluate the codes in ``indicators.md``'s "Constraint checks" table.

    Status is ``pass``, ``fail`` or ``not_checked``. ``not_checked`` is a real
    outcome, not a soft failure: several of these cannot be decided from the reply
    alone, and reporting them as passes would be the same conflation the rest of
    this repository works to avoid.
    """
    codes = plan.get("constraints") or []
    if plan.get("acts_withheld"):
        return []
    results: list[dict[str, str]] = []

    def add(code: str, status: str, detail: str) -> None:
        if code in codes:
            results.append({"code": code, "status": status, "detail": detail})

    # no_fabrication needs the *conversation*, not the signal packet. An earlier
    # version of this check compared quotations against the packet's one-line
    # stance claim and evidence, which flagged an agent paraphrasing its own prior
    # position as a fabrication — a false positive on the constraint whose whole
    # purpose is to catch invented sources. The packet cannot adjudicate this, so
    # without a supplied context the check reports that it did not run.
    if context_text is None:
        add(
            "no_fabrication",
            "not_checked",
            "no --context supplied; the signal packet is not the conversation and cannot resolve a quotation",
        )
    else:
        quoted = [chunk for chunk in _quoted_spans(reply_text) if len(chunk) >= 6]
        urls = _urls(reply_text)
        unresolved = [chunk for chunk in quoted if chunk not in context_text]
        dangling = [url for url in urls if url not in context_text]
        if unresolved or dangling:
            add(
                "no_fabrication",
                "fail",
                f"{len(unresolved)} quoted span(s) and {len(dangling)} URL(s) absent from the supplied context",
            )
        else:
            add(
                "no_fabrication",
                "pass",
                f"{len(quoted)} quoted span(s) and {len(urls)} URL(s) resolve to the context",
            )

    lowered = reply_text.lower()
    traces = [cue for cue in REASONING_TRACE_CUES if cue in lowered]
    add(
        "no_hidden_chain_of_thought",
        "fail" if traces else "pass",
        f"reasoning-trace phrasing found: {traces[:2]}" if traces else "no reasoning-trace phrasing",
    )

    if "report_uncertainty_explicitly" in codes:
        count = int(coding.get("uncertainty_term") or 0)
        add(
            "report_uncertainty_explicitly",
            "pass" if count >= 1 else "fail",
            f"uncertainty_term = {count}",
        )

    if "discount_requires_checkable_reason" in codes:
        discount = bool(coding.get("source_discount"))
        quality = bool(coding.get("source_quality_mention"))
        if not discount:
            add("discount_requires_checkable_reason", "pass", "no source discount coded")
        elif quality:
            add("discount_requires_checkable_reason", "pass", "discount accompanied by a method-based reason")
        else:
            add(
                "discount_requires_checkable_reason",
                "fail",
                "source_discount coded with no source_quality_mention in the same reply",
            )

    if "no_silent_retraction" in codes:
        delta = coding.get("claim_strength_delta")
        explicit = bool(coding.get("explicit_stance_change"))
        hedged = int(coding.get("certainty_downgrade") or 0) > 0
        if not isinstance(delta, (int, float)) or delta >= 0:
            add("no_silent_retraction", "not_checked", "claim_strength_delta unavailable or not negative")
        elif explicit or hedged:
            add("no_silent_retraction", "pass", "weakening is announced or hedged")
        else:
            add("no_silent_retraction", "fail", "claim weakened with no acknowledgement and no hedge")

    if "disclose_pressure_driver" in codes:
        hits = [cue for cue in PRESSURE_CUES if cue in reply_text]
        add(
            "disclose_pressure_driver",
            "pass" if hits else "fail",
            f"pressure referenced ({hits[0]!r})" if hits else "pressure not referenced",
        )

    if "fidelity_not_advice" in codes:
        # The label lives on the card, not in the reply, so this is checkable only
        # when the card is available. Recorded rather than passed by default.
        add("fidelity_not_advice", "not_checked", "the branch label is a card artefact, not reply text")

    return results


def _quoted_spans(text: str) -> list[str]:
    spans: list[str] = []
    for opener, closer in (("「", "」"), ("“", "”"), ("\"", "\""), ("『", "』")):
        start = 0
        while True:
            left = text.find(opener, start)
            if left < 0:
                break
            right = text.find(closer, left + 1)
            if right < 0:
                break
            spans.append(text[left + 1 : right].strip())
            start = right + 1
    return spans


def _urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)）】」”\"']+", text)


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    act_expected: Counter[str] = Counter()
    act_realised: Counter[str] = Counter()
    act_unchecked: Counter[str] = Counter()
    violations: dict[str, Counter[str]] = defaultdict(Counter)
    indicators: dict[str, list[float]] = defaultdict(list)
    agree = 0
    comparable = 0

    for row in rows:
        for act in row["acts"]:
            if not act["checked"]:
                act_unchecked[act["act"]] += 1
                continue
            act_expected[act["act"]] += 1
            if act["realised"]:
                act_realised[act["act"]] += 1
        for violation in row["violations"]:
            violations[violation["code"]][violation["status"]] += 1
        for name in INDICATOR_NAMES:
            value = row["indicators"].get(name)
            if isinstance(value, (int, float)):
                indicators[name].append(float(value))
        if row["planned_change"] is not None:
            comparable += 1
            if row["agrees"]:
                agree += 1

    return {
        "replies": len(rows),
        "act_expected": dict(act_expected),
        "act_realised": dict(act_realised),
        "act_unchecked": dict(act_unchecked),
        "violations": {code: dict(counts) for code, counts in violations.items()},
        "indicator_means": {
            name: (sum(values) / len(values)) for name, values in indicators.items() if values
        },
        "agreement_n": comparable,
        "agreement_rate": (agree / comparable) if comparable else None,
    }


def render(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Response coding",
        "",
        "Generated by `python scripts/score_responses.py --write-report`.",
        "",
        "> **What this report cannot show.** It reports agreement between two",
        "> instruments that are both unvalidated: a lexicon-based coder and a",
        "> response plan. A high act-realisation rate says the reply did what the plan",
        "> asked, not that the plan asked for the right thing; a low one says the two",
        "> disagree, not which is wrong. `claim_strength_delta` rests on an explicit",
        "> placeholder, and the lexicons carry a `_provenance` note saying they are",
        "> uncalibrated. Nothing here is evidence about construct validity, and nothing",
        "> here substitutes for the inter-rater protocol in `references/codebook.md`.",
        "",
        f"- replies coded: {summary['replies']}",
    ]
    if summary["agreement_rate"] is None:
        lines.append("- planned-vs-observed agreement: not computable (no replies)")
    else:
        lines.append(
            f"- planned-vs-observed agreement: {summary['agreement_rate']:.3f} "
            f"over {summary['agreement_n']} replies"
        )
    lines.append("")

    lines += [
        "## Act realisation",
        "",
        "| act | expected in | realised | rate |",
        "|---|---|---|---|",
    ]
    for act in sorted(summary["act_expected"], key=lambda a: -summary["act_expected"][a]):
        expected = summary["act_expected"][act]
        realised = summary["act_realised"].get(act, 0)
        lines.append(f"| `{act}` | {expected} | {realised} | {realised / expected:.3f} |")
    if not summary["act_expected"]:
        lines.append("| _none_ | 0 | 0 | — |")

    if summary["act_unchecked"]:
        lines += [
            "",
            "### Acts with no machine-readable expectation",
            "",
            "These were requested by a plan but `indicators.md`'s act-to-indicator table",
            "lists no checkable prediction for them, so they are excluded from the rates",
            "above rather than counted as failures:",
            "",
        ]
        lines += [f"- `{act}` ({count} replies)" for act, count in sorted(summary["act_unchecked"].items())]

    lines += [
        "",
        "## Constraint checks",
        "",
        "| code | pass | fail | not checked | violation rate |",
        "|---|---|---|---|---|",
    ]
    for code in sorted(summary["violations"]):
        counts = summary["violations"][code]
        passes = counts.get("pass", 0)
        fails = counts.get("fail", 0)
        unchecked = counts.get("not_checked", 0)
        denominator = passes + fails
        rate = f"{fails / denominator:.3f}" if denominator else "—"
        lines.append(f"| `{code}` | {passes} | {fails} | {unchecked} | {rate} |")
    if not summary["violations"]:
        lines.append("| _none_ | 0 | 0 | 0 | — |")

    lines += [
        "",
        "A `not_checked` cell is not a pass. `fidelity_not_advice` lives on the card",
        "rather than in the reply, and `no_fabrication` needs the supplied context;",
        "both are recorded as unchecked when they cannot be decided.",
        "",
        "## Indicator means",
        "",
        "Descriptive only. Branch discriminability is a separate, blind test — see",
        "`references/indicators.md` — and reporting per-branch means is not a",
        "substitute for it.",
        "",
        "| indicator | mean |",
        "|---|---|",
    ]
    for name in INDICATOR_NAMES:
        if name in summary["indicator_means"]:
            lines.append(f"| `{name}` | {summary['indicator_means'][name]:.3f} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--pairs", help="directory of {reply_text, evaluation} JSON files")
    source.add_argument("--log", help="JSONL log written with logging.include_reply: true")
    parser.add_argument(
        "--context",
        help=(
            "the conversation text the replies were answering. Required for the "
            "no_fabrication check: the signal packet is not the conversation, so "
            "without this the check reports not_checked rather than guessing"
        ),
    )
    parser.add_argument("--config")
    parser.add_argument("--write-report", action="store_true", help="write eval/responses.md")
    parser.add_argument("--strict", action="store_true", help="exit non-zero on any constraint violation")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(Path(args.config) if args.config else None)
    context_text = Path(args.context).read_text(encoding="utf-8") if args.context else None

    pairs: list[dict[str, Any]] = []
    if args.pairs:
        pairs = read_pairs(Path(args.pairs))
    elif args.log:
        pairs = read_log(Path(args.log))

    if not pairs:
        print("nothing to score: no replies supplied.")
        print("Pass --pairs <dir> of {reply_text, evaluation} JSON files, or --log <jsonl>")
        print("written with logging.include_reply: true. Both are produced by running")
        print("the skill with --reply-file; see references/operations.md.")
        if args.write_report:
            write_text(REPORT_PATH, render(summarise([]), []))
            print(f"wrote {REPORT_PATH}")
        return 0

    rows = [score_pair(pair, config, context_text) for pair in pairs]
    summary = summarise(rows)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"replies coded: {summary['replies']}")
        if summary["agreement_rate"] is not None:
            print(
                f"planned-vs-observed agreement: {summary['agreement_rate']:.3f} "
                f"over {summary['agreement_n']} replies"
            )
        print()
        print("act                          expected  realised   rate")
        print("---------------------------  --------  --------  ------")
        for act in sorted(summary["act_expected"], key=lambda a: -summary["act_expected"][a]):
            expected = summary["act_expected"][act]
            realised = summary["act_realised"].get(act, 0)
            print(f"{act:<27}  {expected:>8}  {realised:>8}  {realised / expected:.3f}")
        print()
        print("constraint                            pass  fail  unchecked")
        print("------------------------------------  ----  ----  ---------")
        for code in sorted(summary["violations"]):
            counts = summary["violations"][code]
            print(
                f"{code:<36}  {counts.get('pass', 0):>4}  {counts.get('fail', 0):>4}  "
                f"{counts.get('not_checked', 0):>9}"
            )

    if args.write_report:
        write_text(REPORT_PATH, render(summary, rows))
        print()
        print(f"wrote {REPORT_PATH}")

    failures = sum(
        counts.get("fail", 0) for counts in summary["violations"].values()
    )
    if failures and args.strict:
        print()
        print(f"{failures} constraint violation(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
