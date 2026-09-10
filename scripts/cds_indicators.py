"""The indicator coder: reply text in, coded indicator values out.

What this module is for
-----------------------
``references/indicators.md`` is the measurement layer of Study 1. The engine's
``response_plan.language_acts`` is a **prediction**; the indicators are the
**observation**, and agreement between the two is a result. If the only evidence
that a ``qualify`` response qualified were the engine's own
``recommended_strategy`` field, the instrument would be grading itself.

This module is the observation half. It is deliberately small and dumb: a
deterministic lexicon scan over clauses, with the ambiguity rules at
``indicators.md:58-67`` implemented as explicit branches. No model is called, no
network, no randomness, no clock. The same reply text codes identically on every
machine, which is what lets the coder's agreement with a human coder be reported
as a number instead of an anecdote.

What it is not
--------------
* It is not a classifier of intent. ``consonant_addition`` is coded as "a new
  supporting consideration absent from the supplied evidence", not as "the agent
  is rationalising". The construct reading belongs to the analyst, not here.
* It is not calibrated. :func:`rate_claim_strength` is an explicit placeholder;
  see its docstring.
* It does not read the response plan in order to decide anything. ``plan`` is
  accepted and its predicted acts are recorded in ``_evidence``, but coding stays
  blind to condition (``indicators.md:49-50``). A coder that peeked at the plan
  would make act-realisation agreement circular, which is the one thing this
  layer exists to prevent.

The rules that matter most, and how they are implemented
--------------------------------------------------------
1. ``certainty_downgrade`` is ``count(hedges) - count(boosters)`` and may be
   negative (``indicators.md:30``).
2. A conditional that names no condition ("如果情况有变") does **not** satisfy
   ``conditional_marker`` and is recorded as a failed act
   (``indicators.md:64``). The coder therefore reports failed acts, not only
   present ones (``indicators.md:55``).
3. Source criticism that names a method, sample or track record is
   ``source_quality_mention`` and **not** ``source_discount``
   (``indicators.md:65``). The check is clause-scoped: a discount cue is only
   coded when the same clause names no method-based reason.
4. A hedge inside a quotation of someone else is not counted; coding is
   attributed to the agent's own assertions only (``indicators.md:62``). Lexicon
   coding is quote-excluded throughout, with two deliberate exceptions:
   counter-evidence cues may be quoted, because a restated counterargument inside
   quotation marks is still a mention (``indicators.md:63``).
5. ``importance_denial`` requires order: a concession must precede the relevance
   minimiser (``indicators.md:40``). The reverse order codes 0.
6. ``consonant_addition`` requires ``signals``; it is coded 0 with an explanatory
   ``_evidence`` note when no packet is supplied, because "absent from the
   evidence" is not decidable without the evidence.
7. ``unacknowledged_softening`` is coded from the text — a weakening cue (or a
   hedge) sitting on a clause that carries the agent's own claim, with no
   acknowledgement of change anywhere in the reply. A negative
   ``claim_strength_delta`` alone does not trigger it, because that rating comes
   from the uncalibrated placeholder below and would otherwise code silent drift
   in a reply that restates its claim verbatim.

The ``_evidence`` trace
-----------------------
:func:`code_reply` returns the 15 indicator variables plus ``_evidence``, a list
of records ``{indicator, clause_index, matched, clause}`` (plus ``note`` where
there is something to say). ``clause_index`` indexes :func:`split_clauses` on the
same text; ``-1`` means the record is reply-level and belongs to no single
clause. Note prefixes carry the record's kind:

* ``"failed act:"`` — the act was expected and not realised (``indicators.md:55``,
  ``:64``).
* ``"not coded:"`` — the cue fired but a rule in the scheme says the indicator
  stays 0 (the source-quality boundary at ``indicators.md:65``, the ordering
  requirement of ``importance_denial``, an acknowledged change that keeps
  ``unacknowledged_softening`` at 0).
* ``"explains:"`` — why an indicator is 0 or ``None``.
* ``"expected_act:"`` — a prediction copied out of ``response_plan.language_acts``.
  These never affect a coded value. Such a record may carry the pseudo-indicator
  ``_act`` when the table lists no machine-readable expectation for that act.

:func:`evidence_for` returns the firing records for one indicator, filtered of
those kinds, so the traceability claim ("every non-zero flag or count is traceable
to a clause and a lexicon entry") is machine-checkable.

Lexicon mechanics, including one trap
-------------------------------------
Lexemes are matched longest-first with a single consumption mask shared across
categories, so a longer entry suppresses any shorter entry it overlaps. That is
what keeps ``不一定`` (a hedge) from also counting as ``一定`` (a booster) and
``在一定程度上`` from counting as ``一定``. The consequence to remember when
editing ``config/lexicon.<lang>.json``: an entry listed in **two** categories
fires **both**, but a *longer* entry that contains a shorter one suppresses the
shorter one everywhere — including in another category. A compound that should
count for two indicators must therefore be listed in both. ASCII entries are
matched at word boundaries (so ``if`` cannot fire inside ``verify``), while CJK
entries are matched as substrings, which is the intended behaviour for a language
without spaces. Lexemes are data, not claims of linguistic authority; see
``_provenance`` in each lexicon file.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from cds_config import read_text

REPO_ROOT = Path(__file__).resolve().parent.parent
LEXICON_DIR = REPO_ROOT / "config"

# Canonical order of the 15 variables, following the order of the table in
# references/indicators.md so a reader can compare the two line by line. The
# first fourteen rows of that table yield fifteen variables: the two-sided
# weighing row names counterevidence_mention and support_mention, and each is
# coded separately.
INDICATOR_NAMES: tuple[str, ...] = (
    "mark_conflict",
    "certainty_downgrade",
    "counterevidence_mention",
    "support_mention",
    "conditional_marker",
    "explicit_stance_change",
    "reason_step_count",
    "source_quality_mention",
    "uncertainty_term",
    "claim_strength_delta",
    "verification_action",
    "source_discount",
    "importance_denial",
    "consonant_addition",
    "unacknowledged_softening",
)

# The lexeme categories a lexicon file may define. Metadata keys in the file
# start with an underscore and are ignored here: they are for the human editor.
LEXICON_CATEGORIES: tuple[str, ...] = (
    "hedges",
    "boosters",
    "uncertainty_terms",
    "conflict_markers",
    "conditional_markers",
    "condition_naming_cues",
    "source_quality_cues",
    "source_discount_cues",
    "verification_cues",
    "consonant_addition_cues",
    "importance_minimisers",
    "concession_markers",
    "stance_change_markers",
    "softening_cues",
    "change_acknowledgement_cues",
    "reason_step_markers",
    "quote_pairs",
)

# The three record kinds that are *not* firings. Kept here rather than in the
# lexicon because they describe the record format, not the language.
NON_FIRING_NOTE_PREFIXES: tuple[str, ...] = ("failed act:", "explains:", "expected_act:", "not coded:")

# ---------------------------------------------------------------------------
# Vocabulary that is structural rather than lexical
# ---------------------------------------------------------------------------
# These cue sets name the *move* a reply is making, not a word whose meaning is
# at issue, and they are matched against clause structure rather than counted.
# They live in code so the lexicon files stay exactly the shape the indicators
# table defines; a human coder reviewing them should treat them as reviewable
# defaults, not as fixed constants.

# Cues that a clause carries the agent's own claim. Used to decide whether a
# conditional is "attached to the claim" (indicators.md:32) and as the
# rateability gate of rate_claim_strength.
_CLAIM_CUES: tuple[str, ...] = (
    "我的判断", "我的结论", "我的看法", "我的立场", "我认为", "我建议", "我倾向于",
    "立场", "结论", "判断", "仍然可用", "仍然成立", "依然成立", "仍然可靠", "可用",
    "可靠", "成立", "不变", "建议", "会改变", "就需要修正", "我依然", "我仍然",
    "my judgment", "my conclusion", "my view", "my position", "i think", "i recommend",
    "the stance", "still holds", "still works", "remains", "reliable", "usable",
)

# Content that tells against the agent's own stance. Combined with a
# counter-evidence mention it establishes conflict awareness in a reply that
# never uses the word "conflict" (the `mark_conflict_minimally` shape).
_OPPOSING_CUES: tuple[str, ...] = (
    "有问题", "存在缺陷", "重大缺陷", "缺陷", "漏洞", "失败", "不成立", "出错", "有误",
    "风险", "反例", "反面", "不一致", "相左", "冲突", "质疑", "反对", "效果不好",
    "不可靠", "不可信", "站不住脚", "出问题", "会失效", "失效", "崩塌", "fail", "fails",
    "failed", "problem", "problems", "flaw", "defect", "defects", "risk", "contradicts",
    "inconsistent", "invalid", "not credible", "unreliable", "not trustworthy",
    "has an agenda",
)

# Cues that the reply is naming the evidence that tells against its stance.
# Deliberately allowed inside quotations, unlike every lexicon category.
_COUNTEREVIDENCE_CUES: tuple[str, ...] = (
    "反证", "反对意见", "反对的证据", "相反的证据", "反面证据", "你带来的", "你说的",
    "你上面说", "你之前说", "你提到的", "你指出的", "你的质疑", "对方的", "这篇论文",
    "这份材料", "这份报告",
    "这项研究", "这项分析", "这份数据", "新研究", "新证据", "论文", "材料", "报告",
    "研究", "数据", "统计", "质疑", "反驳", "争议", "问题在于",
    "the paper", "the study", "the report", "the finding", "the evidence against",
    "your point", "your objection", "the counterargument", "the data",
)

# Cues that the reply is naming the support for its own position: two-sided
# weighing requires both sides, and this is the side the agent already held.
_SUPPORT_CUES: tuple[str, ...] = (
    "支持", "支撑", "理由", "原因", "经验", "第一手", "一手经验", "优势", "长处",
    "熟悉度", "熟悉", "运维成本", "成本低", "效果好", "我们过去", "我们以前",
    "一直", "仍然成立", "依然成立", "依据", "证据支持", "实测", "实际使用",
    "supports", "in favor", "the reason", "our experience", "first-hand", "advantage",
    "strength", "still holds",
)

# Cues that a consideration was already standing before this reply. A
# consideration the reply itself marks as continuing is a restatement of the
# position's existing basis, not a newly added cognition, and
# indicators.md:41 defines consonant_addition as *new*.
_CONTINUITY_CUES: tuple[str, ...] = (
    "仍然", "依然", "仍旧", "一直", "一贯", "本来就", "此前就", "之前就", "上面说",
    "已经说过", "此前的", "过去的", "之前提到", "前面提到",
    "still", "as before", "as i said", "already", "previously",
)

# Cues that a clause is talking about a *source* rather than about the claim.
# source_discount needs one, so that "这个说法不可信" is not read as discounting
# a source that was never named.
_SOURCE_POINTERS: tuple[str, ...] = (
    "论文", "作者", "来源", "报告", "研究", "材料", "数据", "期刊", "媒体", "网站",
    "官方", "样本", "出处", "统计", "paper", "source", "study", "author", "report",
    "data", "article", "journal", "publisher", "sample",
)

# Conditionals that name no condition, so that conditional_marker is coded *not*
# satisfied and the act is recorded as failed (indicators.md:64).
_GENERIC_CONDITION_FORMS: tuple[str, ...] = (
    "情况有变", "情况变化", "情况改变", "情形有变", "情形变化", "条件有变", "条件变化",
    "有变化", "发生变化", "有需要", "需要的话", "必要时", "如果有变", "如果再变",
    "if things change", "if circumstances change", "if that changes", "if necessary",
    "if needed", "should things change", "in case of change",
)

_NEGATORS: tuple[str, ...] = ("不", "没", "未", "无", "非", "别", "莫", "缺乏")
_EN_NEGATORS: tuple[str, ...] = ("not", "no", "never", "without", "cannot", "n't", "lack")

# Overlap is computed over distinctive terms: CJK bigrams and ASCII tokens of
# three or more characters. Function words carry no evidential content, so they
# are removed before two spans are compared.
_OVERLAP_STOPWORDS: frozenset[str] = frozenset(
    {
        "我们", "你们", "他们", "她们", "这个", "那个", "这些", "那些", "什么", "如果",
        "但是", "不过", "因为", "所以", "而且", "以及", "还是", "就是", "已经", "可以",
        "需要", "没有", "不是", "可能", "一个", "这样", "那样", "之后", "之前", "现在",
        "上面", "下面", "一些", "很多", "非常", "确实", "当然", "另外", "此外", "同时",
        "并且", "于是", "因此", "然而", "其实", "并不", "也就", "的话", "时候", "里面",
        "the", "and", "for", "that", "this", "with", "from", "not", "are", "was", "were",
        "has", "have", "had", "but", "you", "your", "our", "its", "his", "her", "they",
        "them", "there", "here", "what", "when", "which", "will", "would", "can", "could",
        "should", "about", "into", "than", "then", "more", "most", "some", "any", "all",
        "one", "two", "also", "find", "found", "does", "did", "how", "why", "who",
    }
)

# Clause splitting. One clause is one finite assertion; coordination joins two
# (indicators.md:46-47), so a coordinator starts a new clause and a nominal
# enumeration mark ("、") does not.
_SENTENCE_BOUNDARY = "。！？!?；;\n\r"
_COLON_OR_DASH = "：:—…"
_COMMA = "，"
_COORDINATORS: dict[str, tuple[str, ...]] = {
    "zh": (
        "但是", "但", "不过", "然而", "可是", "只是", "而是", "而且", "并且", "所以",
        "因此", "因而", "于是", "同时", "另外", "此外", "反之", "也就是说", "一方面",
        "另一方面", "即便如此",
    ),
    "en": (
        "however", "therefore", "nevertheless", "but", "although", "whereas",
        "moreover", "furthermore", "besides", "instead",
    ),
}
_MARKUP_CHARS = "*`#>|—… \t\u3000\u200b"

# Commitment-style anchors of the rate_claim_strength placeholder. Weights, not
# measurements: see the docstring of that function.
_STRENGTH_BASELINE = 0.50
_STRENGTH_BOOSTER_STEP = 0.12
_STRENGTH_HEDGE_STEP = 0.12
_STRENGTH_CONDITIONAL_STEP = 0.10
_STRENGTH_SOFTENING_STEP = 0.08
_STRENGTH_CAP = 2

# ---------------------------------------------------------------------------
# Built-in default lexicon
# ---------------------------------------------------------------------------
# A deliberately compact fallback, per language, so that a missing or malformed
# config/lexicon.<lang>.json degrades to something usable instead of crashing a
# corpus run. The shipped files are the authoritative, fuller lexicon; nothing
# here is a claim about which words matter.
_DEFAULT_LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "zh": {
        "hedges": ("可能", "也许", "或许", "大概", "似乎", "好像", "看起来", "恐怕", "未必", "不一定"),
        "boosters": ("一定", "必然", "肯定", "无疑", "显然", "确实", "完全", "绝对"),
        "uncertainty_terms": ("不确定", "无法判断", "未确认", "尚未", "存疑", "有待", "不清楚", "未知"),
        "conflict_markers": ("冲突", "矛盾", "相反", "不一致", "对立", "张力", "不符", "相悖"),
        "conditional_markers": ("如果", "假如", "若", "倘若", "只要", "除非", "一旦", "条件下"),
        "condition_naming_cues": ("条件下", "前提下", "场景", "部署", "样本", "规模", "指标", "成本"),
        "source_quality_cues": ("方法", "样本量", "采样", "数据来源", "第一手", "同行评审", "独立来源", "复现"),
        "source_discount_cues": ("不可信", "不可靠", "有偏见", "有立场", "夸大", "不专业", "来源可疑", "不严谨"),
        "verification_cues": ("核查", "核实", "验证", "复核", "检查", "复现", "交叉验证", "对照"),
        "consonant_addition_cues": ("而且", "另外", "此外", "更重要的是", "况且", "至少", "毕竟", "同时"),
        "importance_minimisers": ("不重要", "无关紧要", "不足以", "不改变结论", "影响有限", "意义不大", "可以忽略", "次要"),
        "concession_markers": ("确实", "我承认", "我同意", "我记下了", "不可否认", "有道理", "没错", "我接受"),
        "stance_change_markers": ("我修正", "我改变看法", "我改变判断", "我不再认为", "我收回", "更正", "我现在的判断是", "立场发生变化"),
        "softening_cues": ("收窄", "下调", "弱化", "打折扣", "缓和", "不再那么", "没那么", "更谨慎"),
        "change_acknowledgement_cues": ("收窄", "下调", "我调整", "需要修正", "更正", "我更新", "我改变", "修正我的说法"),
        "reason_step_markers": ("因为", "由于", "所以", "因此", "因而", "理由是", "理由", "原因是"),
        "quote_pairs": ("「」", "『』", "“”", "‘’", "\"\"", "''"),
    },
    "en": {
        "hedges": ("maybe", "perhaps", "possibly", "probably", "seems", "appears", "roughly", "somewhat"),
        "boosters": ("certainly", "definitely", "obviously", "clearly", "undoubtedly", "absolutely", "proven"),
        "uncertainty_terms": ("uncertain", "unclear", "unknown", "not confirmed", "cannot tell", "pending"),
        "conflict_markers": ("conflict", "contradiction", "contradicts", "inconsistent", "at odds", "tension"),
        "conditional_markers": ("if", "unless", "as long as", "provided that", "conditional on", "once"),
        "condition_naming_cues": ("condition", "scenario", "deployment", "sample", "configuration", "threshold"),
        "source_quality_cues": ("method", "sample size", "sampling", "dataset", "first-hand", "peer-reviewed", "replication"),
        "source_discount_cues": ("not credible", "unreliable", "biased", "has an agenda", "exaggerates", "anonymous"),
        "verification_cues": ("verify", "verification", "check", "cross-check", "audit", "replicate", "spot-check"),
        "consonant_addition_cues": ("moreover", "furthermore", "besides", "what is more", "in addition", "at least"),
        "importance_minimisers": ("not important", "irrelevant", "minor", "edge case", "does not change", "negligible"),
        "concession_markers": ("i admit", "i agree", "granted", "indeed", "fair point", "i concede"),
        "stance_change_markers": ("i was wrong", "i revise", "i no longer think", "i now think", "my position has changed"),
        "softening_cues": ("soften", "moderate", "less certain", "narrow", "tone down", "more cautious"),
        "change_acknowledgement_cues": ("i correct", "correction", "i should revise", "i update", "i overstated"),
        "reason_step_markers": ("because", "since", "therefore", "thus", "hence", "the reason", "as a result"),
        "quote_pairs": ("“”", "‘’", "\"\"", "''", "「」", "『』"),
    },
}


@lru_cache(maxsize=8)
def _read_lexicon_file(path: str) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    """Parse one lexicon file into immutable per-category tuples.

    Returns ``None`` for any failure — missing file, invalid JSON, wrong shape —
    because the documented behaviour is a fallback, not an exception: a research
    tool that dies because a hand-edited data file has a stray comma is a tool
    that loses a corpus run. The file is parsed at most once per process, so an
    edit is picked up by the next run and not by a long-lived one.
    """
    try:
        data = json.loads(read_text(path))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    entries: list[tuple[str, tuple[str, ...]]] = []
    for category in LEXICON_CATEGORIES:
        values = data.get(category)
        if isinstance(values, list):
            cleaned = tuple(sorted({value for value in values if isinstance(value, str) and value}))
            entries.append((category, cleaned))
    return tuple(entries)


def load_lexicon(language: str = "zh") -> dict[str, list[str]]:
    """Load ``config/lexicon.<lang>.json``, falling back to the built-in default.

    Per-category: a category absent from the file falls back to the built-in
    default, while a category present as an empty list stays empty, because an
    empty list is a coder's deliberate decision whereas an absent key is not.
    Unknown or misspelled keys are ignored (a typo therefore reads as "absent"
    and silently falls back — worth knowing before editing a file). Metadata keys
    such as ``_provenance`` are dropped, so the return value is exactly
    :data:`LEXICON_CATEGORIES`, each mapping to a fresh list.
    """
    key = language if isinstance(language, str) and language else "zh"
    loaded = _read_lexicon_file(str(LEXICON_DIR / f"lexicon.{key}.json"))
    from_file = dict(loaded) if loaded else {}
    default = _DEFAULT_LEXICON.get(key) or _DEFAULT_LEXICON["zh"]
    result: dict[str, list[str]] = {}
    for category in LEXICON_CATEGORIES:
        entries = from_file.get(category)
        if entries is None:
            entries = tuple(default.get(category, ()))
        result[category] = list(entries)
    return result


def _normalised(lexicon: dict[str, Any], category: str) -> list[str]:
    values = lexicon.get(category) or []
    return sorted({value.lower() for value in values if isinstance(value, str) and value})


# ---------------------------------------------------------------------------
# Quotation masking and clause splitting
# ---------------------------------------------------------------------------


def _quote_mask(text: str, lexicon: dict[str, Any]) -> list[bool]:
    """Mark every character that sits inside a quotation.

    ``quote_pairs`` holds two-character entries, opener then closer (``「」``,
    ``“”``, ``""``). Identical opener and closer are paired up in order, which is
    what ASCII double quotes require; an unmatched opener is left unmasked rather
    than swallowing the rest of the reply.
    """
    mask = [False] * len(text)
    pairs = lexicon.get("quote_pairs") or []
    for pair in sorted(value for value in pairs if isinstance(value, str) and len(value) == 2):
        opening, closing = pair[0], pair[1]
        if opening == closing:
            positions = [index for index, char in enumerate(text) if char == opening]
            for start, end in zip(positions[0::2], positions[1::2]):
                for index in range(start, end + 1):
                    mask[index] = True
            continue
        cursor = 0
        while True:
            start = text.find(opening, cursor)
            if start < 0:
                break
            end = text.find(closing, start + 1)
            if end < 0:
                break
            for index in range(start, end + 1):
                mask[index] = True
            cursor = end + 1
    return mask


def _coordinators(language: str) -> tuple[str, ...]:
    return _COORDINATORS.get(language, _COORDINATORS["zh"])


def _boundary_cuts(text: str, language: str, mask: list[bool]) -> list[int]:
    """Offsets at which a new clause starts (each cut keeps its punctuation)."""
    length = len(text)
    cuts: set[int] = set()
    for index, char in enumerate(text):
        if mask[index]:
            continue
        if char in _SENTENCE_BOUNDARY or char in _COLON_OR_DASH or char == _COMMA:
            cuts.add(index + 1)
        elif char in ".," and (index + 1 == length or text[index + 1].isspace()):
            cuts.add(index + 1)

    for coordinator in _coordinators(language):
        is_ascii = coordinator.isascii()
        start = text.find(coordinator)
        while start >= 0:
            end = start + len(coordinator)
            spelled_out = (
                not any(mask[start:end])
                and start > 0
                and (not is_ascii or (not text[start - 1].isalnum() and (end == length or not text[end].isalnum())))
            )
            if spelled_out:
                cuts.add(start)
            start = text.find(coordinator, start + 1)
    return sorted(cut for cut in cuts if 0 < cut <= length)


def _trim(text: str, start: int, end: int) -> tuple[str, int]:
    while start < end and text[start] in _MARKUP_CHARS:
        start += 1
    while end > start and text[end - 1] in _MARKUP_CHARS:
        end -= 1
    return text[start:end], start


def _split_with_offsets(text: str, language: str, mask: list[bool]) -> list[tuple[str, int]]:
    """Clauses with the offset at which each one starts in the original text."""
    spans: list[tuple[str, int]] = []
    previous = 0
    for cut in _boundary_cuts(text, language, mask) + [len(text)]:
        clause, offset = _trim(text, previous, cut)
        if clause:
            spans.append((clause, offset))
        previous = cut
    return spans


def split_clauses(text: str, language: str = "zh") -> list[str]:
    """One clause = one finite assertion; coordination joins two.

    A sentence-final or contrastive mark ends a clause (``。``, ``；``, ``，``,
    ``——``, ``：``, ``but``, ``因此`` ...), while a nominal enumeration mark
    (``、``) does not, because the items it joins are not separate assertions.
    Boundaries inside a quotation are not cut points.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    lexicon = load_lexicon(language)
    return [clause for clause, _ in _split_with_offsets(text, language, _quote_mask(text, lexicon))]


def _clause_index(clause_spans: list[tuple[str, int]], offset: int) -> int:
    """Index of the clause holding ``offset``; the next clause if in a gap."""
    for index, (clause, start) in enumerate(clause_spans):
        if start <= offset < start + len(clause):
            return index
        if offset < start:
            return index
    return len(clause_spans) - 1


# ---------------------------------------------------------------------------
# Lexeme and cue matching
# ---------------------------------------------------------------------------


def _haystack(text: str) -> str:
    """Case-folded text when folding preserves length, so offsets stay valid."""
    lowered = text.lower()
    return lowered if len(lowered) == len(text) else text


def _negated_before(text: str, index: int) -> bool:
    """True when the match at ``index`` sits inside a negation.

    A heuristic, and a load-bearing one: without it ``不确定`` feeds ``确定`` and
    ``不足以改变结论`` feeds ``我改变``. It looks back three characters for a
    Chinese negator and at the preceding word for an English one, which will
    misread longer constructions such as "并不是说没有可能" as negated. Worth
    knowing when reading a coding trace; the false negative is visible there.
    """
    window = text[max(0, index - 3):index]
    if any(negator in window for negator in _NEGATORS):
        return True
    words = re.findall(r"[A-Za-z']+", text[max(0, index - 14):index])
    return bool(words) and words[-1].lower() in _EN_NEGATORS


def _is_ascii_word_char(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _spelled_out(haystack: str, start: int, lexeme: str) -> bool:
    """Word-boundary test for ASCII entries.

    Chinese needs no such test, but an English entry is a substring of other
    words more often than not: without this, ``if`` fires inside ``verify`` and
    ``specific``, and ``no`` inside ``not`` and ``north``. ASCII entries are
    therefore accepted only at a word edge; CJK entries are matched as substrings,
    which is the intended behaviour for a language without spaces.
    """
    if not lexeme.isascii():
        return True
    end = start + len(lexeme)
    before_ok = start == 0 or not _is_ascii_word_char(haystack[start - 1])
    after_ok = end >= len(haystack) or not _is_ascii_word_char(haystack[end])
    return before_ok and after_ok


def _winning_spans(text: str, lexicon: dict[str, Any], mask: list[bool]) -> list[tuple[int, int, str]]:
    """Longest-first lexeme matches, with overlapping shorter matches suppressed.

    Each winner is ``(start, end, verbatim_span)``: the third element is the text
    as the reply wrote it, not the lexicon entry, so an English match records
    ``If`` rather than ``if`` and a trace can always be checked against the reply.

    The consumption mask is shared across categories on purpose: it is what stops
    ``在一定程度上`` from also counting as the booster ``一定``. See the module
    docstring for the consequence when a compound should fire two indicators.
    """
    haystack = _haystack(text)
    lexemes = sorted(
        {value for category in LEXICON_CATEGORIES for value in _normalised(lexicon, category)},
        key=lambda value: (-len(value), value),
    )
    consumed = [False] * len(text)
    winners: list[tuple[int, int, str]] = []
    for lexeme in lexemes:
        start = haystack.find(lexeme)
        while start >= 0:
            end = start + len(lexeme)
            if (
                not any(consumed[start:end])
                and not any(mask[start:end])
                and _spelled_out(haystack, start, lexeme)
                and not _negated_before(text, start)
            ):
                for index in range(start, end):
                    consumed[index] = True
                winners.append((start, end, text[start:end]))
            start = haystack.find(lexeme, start + 1)
    return sorted(winners)


def _credit(winners: list[tuple[int, int, str]], lexicon: dict[str, Any]) -> dict[str, list[tuple[int, int, str]]]:
    """Assign each winning span to every category that lists that exact lexeme."""
    credited: dict[str, list[tuple[int, int, str]]] = {category: [] for category in LEXICON_CATEGORIES}
    for category in LEXICON_CATEGORIES:
        known = set(_normalised(lexicon, category))
        credited[category] = [span for span in winners if span[2].lower() in known]
    return credited


def _cue_hits(
    text: str,
    cues: tuple[str, ...],
    mask: list[bool],
    *,
    allow_quoted: bool = False,
) -> list[tuple[int, int, str]]:
    """Occurrences of a structural cue set, longest-first and non-overlapping."""
    haystack = _haystack(text)
    consumed = [False] * len(text)
    hits: list[tuple[int, int, str]] = []
    for cue in sorted({value.lower() for value in cues}, key=lambda value: (-len(value), value)):
        start = haystack.find(cue)
        while start >= 0:
            end = start + len(cue)
            quoted = any(mask[start:end])
            if (
                not any(consumed[start:end])
                and (allow_quoted or not quoted)
                and _spelled_out(haystack, start, cue)
                and not _negated_before(text, start)
            ):
                for index in range(start, end):
                    consumed[index] = True
                hits.append((start, end, text[start:end]))
            start = haystack.find(cue, start + 1)
    return sorted(hits)


def _distinctive_terms(text: str) -> frozenset[str]:
    """CJK bigrams plus ASCII tokens of length >= 3, minus function words.

    Comparing spans by these terms is how "absent from the evidence" (line 41)
    and "restated from earlier in the reply" are decided without a parser.
    """
    bigrams = {
        run[index:index + 2]
        for run in re.findall(r"[\u4e00-\u9fff]+", text)
        for index in range(len(run) - 1)
    }
    tokens = set(re.findall(r"[a-z0-9%]{3,}", text.lower()))
    return frozenset((bigrams | tokens) - _OVERLAP_STOPWORDS)


def _evidence_terms(signals: dict[str, Any] | None) -> frozenset[str]:
    """Distinctive terms of the supplied evidence claims and quotations."""
    if not signals:
        return frozenset()
    terms: set[str] = set()
    for item in signals.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        for key in ("claim", "quote"):
            value = item.get(key)
            if isinstance(value, str):
                terms |= _distinctive_terms(value)
    return frozenset(terms)


# ---------------------------------------------------------------------------
# Evidence records
# ---------------------------------------------------------------------------


def _record(
    evidence: list[dict[str, Any]],
    clause_spans: list[tuple[str, int]],
    indicator: str,
    offset: int | None,
    matched: str,
    note: str | None = None,
) -> None:
    index = _clause_index(clause_spans, offset) if offset is not None else -1
    clause = clause_spans[index][0] if 0 <= index < len(clause_spans) else ""
    entry: dict[str, Any] = {
        "indicator": indicator,
        "clause_index": index,
        "matched": matched,
        "clause": clause,
    }
    if note:
        entry["note"] = note
    evidence.append(entry)


def is_firing_record(record: dict[str, Any]) -> bool:
    """True when a record is a firing rather than a failed act, a note or a prediction."""
    note = record.get("note") or ""
    return record.get("clause_index", -1) >= 0 and not note.startswith(NON_FIRING_NOTE_PREFIXES)


def evidence_for(result: dict[str, Any], indicator: str) -> list[dict[str, Any]]:
    """Firing records for one indicator, so a coded value can be traced to a clause."""
    return [
        record
        for record in result.get("_evidence") or []
        if record.get("indicator") == indicator and is_firing_record(record)
    ]


# ---------------------------------------------------------------------------
# Claim strength
# ---------------------------------------------------------------------------


def _rate_from_parts(
    claim_present: bool,
    hedges: int,
    boosters: int,
    conditionals: int,
    softening: int,
) -> float | None:
    if not claim_present:
        return None
    score = _STRENGTH_BASELINE
    score += _STRENGTH_BOOSTER_STEP * min(boosters, _STRENGTH_CAP)
    score -= _STRENGTH_HEDGE_STEP * min(hedges, _STRENGTH_CAP)
    score -= _STRENGTH_CONDITIONAL_STEP * min(conditionals, _STRENGTH_CAP)
    score -= _STRENGTH_SOFTENING_STEP * min(softening, _STRENGTH_CAP)
    return round(min(max(score, 0.0), 1.0), 4)


def rate_claim_strength(text: str, language: str = "zh", lexicon: dict[str, Any] | None = None) -> float | None:
    """Rate the commitment strength of a text's central claim on a 0-1 scale.

    **This is a placeholder, not a measurement.** ``indicators.md:51-53`` requires
    ``claim_strength_delta`` to be a rated 0-1 before/after difference on the
    codebook's commitment-style anchors, i.e. a judgement made by a coder. This
    function approximates that judgement from commitment-style cues alone, and the
    approximation has not been validated against anything. It must be calibrated
    against the human coding in the inter-rater protocol before any number it
    produces is reported; until then it is useful for the *direction* of a shift
    and for making the coding reproducible, not for its magnitude.

    Two decisions make the approximation less wrong than a whole-reply word count.
    First, hedges and boosters count only where they sit on a clause that carries
    the agent's own claim, because a hedge attached to the counter-evidence is a
    statement about the evidence and not about the claim. Second, conditional
    framing and softening cues each subtract a fixed step, since both lower the
    commitment a reader can rely on. Returns ``None`` when the text carries no
    claim cue at all, which is the honest answer for a reply that commits to
    nothing.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    active = lexicon if lexicon is not None else load_lexicon(language)
    mask = _quote_mask(text, active)
    clause_spans = _split_with_offsets(text, language, mask)
    credited = _credit(_winning_spans(text, active, mask), active)
    claim_hits = _cue_hits(text, _CLAIM_CUES, mask)
    claim_clauses = {_clause_index(clause_spans, hit[0]) for hit in claim_hits}
    conditional_clauses = {_clause_index(clause_spans, hit[0]) for hit in credited["conditional_markers"]}
    return _rate_from_parts(
        bool(claim_hits),
        _scoped(credited["hedges"], clause_spans, claim_clauses),
        _scoped(credited["boosters"], clause_spans, claim_clauses),
        len(conditional_clauses),
        _scoped(credited["softening_cues"], clause_spans, claim_clauses),
    )


def _scoped(
    hits: list[tuple[int, int, str]],
    clause_spans: list[tuple[str, int]],
    clause_indexes: set[int],
) -> int:
    """How many of ``hits`` fall in one of ``clause_indexes``."""
    return sum(1 for hit in hits if _clause_index(clause_spans, hit[0]) in clause_indexes)


# ---------------------------------------------------------------------------
# language_acts -> expected indicators
# ---------------------------------------------------------------------------
# Machine-readable transcription of the table at indicators.md:74-96. The
# predicate vocabulary is fixed by the module's contract: "present" / "positive"
# / "ge2" / "nonzero" / "absent". Two consequences of that fixed vocabulary are
# worth stating rather than hiding:
#
# * The table's inequality `claim_strength_delta < 0` is recorded as "nonzero",
#   because no direction predicate exists. The direction is lost in the
#   machine-readable form and is kept in _PROSE_ONLY_EXPECTATIONS.
# * Rows whose expectation is prose only ("concession of the evidence's content",
#   "stance repeated; delta ≈ 0") map to an empty dict rather than to a
#   fabricated predicate. An act mapping to {} means "the table predicts
#   something this vocabulary cannot express", not "no act was expected".
_EXPECTED_INDICATORS: dict[str, dict[str, str]] = {
    "mark_conflict": {"mark_conflict": "present"},
    "mark_conflict_minimally": {"mark_conflict": "present", "counterevidence_mention": "absent"},
    "mark_indeterminacy": {"mark_conflict": "present", "uncertainty_term": "present", "explicit_stance_change": "absent"},
    "acknowledge_counterevidence": {"counterevidence_mention": "present"},
    "reduce_certainty": {"certainty_downgrade": "positive"},
    "conditional_acceptance": {"conditional_marker": "present"},
    "state_stance_change": {"explicit_stance_change": "present", "claim_strength_delta": "nonzero"},
    "give_reason_chain": {"reason_step_count": "ge2"},
    "give_verification_path": {"verification_action": "present"},
    "state_what_would_change_mind": {"conditional_marker": "present", "verification_action": "present"},
    "discount_source": {"source_discount": "present", "source_quality_mention": "present"},
    "shift_doubt_to_evidence": {"uncertainty_term": "present"},
    "accept_fact": {},
    "deny_importance": {"importance_denial": "present"},
    "add_consonant_cognition": {"consonant_addition": "present"},
    "smooth_apparent_inconsistency": {"explicit_stance_change": "absent", "importance_denial": "absent"},
    "soften_claim": {"claim_strength_delta": "nonzero"},
    "avoid_explicit_retraction": {"claim_strength_delta": "nonzero", "explicit_stance_change": "absent"},
    "acknowledge_pressure": {},
    "restate_stance": {},
    "state_evidence_basis": {"source_quality_mention": "present"},
    # Named in `response_plan.language_acts` (scripts/cds_evaluator.py) but absent
    # from the indicators table. They map to {} so a plan using them is not read
    # as either satisfied or violated; see _PROSE_ONLY_EXPECTATIONS.
    "withhold_conclusion": {},
    "state_competing_readings": {},
}

# What the table expects that no predicate above captures. Recorded so the gap is
# visible to the analyst instead of being silently dropped.
_PROSE_ONLY_EXPECTATIONS: dict[str, str] = {
    "mark_conflict_minimally": "the table qualifies mark_conflict as weak; a flag cannot carry degree",
    "shift_doubt_to_evidence": "the expectation is that the uncertainty term attaches to the evidence rather than to the claim",
    "accept_fact": "a concession of the evidence's content; not a flag in this scheme",
    "acknowledge_pressure": "an explicit mention of the user's insistence; not a flag in this scheme",
    "restate_stance": "the stance is repeated and claim_strength_delta is approximately zero; no predicate expresses 'approximately'",
    "soften_claim": "the table's inequality is claim_strength_delta < 0; recorded as nonzero because the predicate set is fixed",
    "avoid_explicit_retraction": "the table's inequality is claim_strength_delta < 0; recorded as nonzero because the predicate set is fixed",
    "withhold_conclusion": "the act appears in response plans but has no row in the indicators table",
    "state_competing_readings": "the act appears in response plans but has no row in the indicators table",
}


def expected_indicators(language_act: str) -> dict[str, str]:
    """From indicators.md's 'language_acts -> expected indicators' table.

    Returns ``{indicator_name: predicate}`` where the predicate is one of
    ``present``, ``positive``, ``ge2``, ``nonzero``, ``absent``. For a flag,
    ``present`` means 1 and ``absent`` means 0; for a count, ``present`` and
    ``positive`` mean at least 1, ``ge2`` means at least 2, and ``absent`` means
    0. ``claim_strength_delta`` has no predicate for a direction or for
    "approximately zero", so those parts of the table are recorded in
    ``_PROSE_ONLY_EXPECTATIONS`` instead of being invented here.

    An act the table does not list raises ``ValueError``: returning an empty
    mapping would make a missing row look like a satisfied prediction, which is
    exactly the failure mode this layer exists to expose.
    """
    if language_act not in _EXPECTED_INDICATORS:
        raise ValueError(
            f"unknown language_act {language_act!r}: the indicators table in "
            "references/indicators.md has no row for it"
        )
    return dict(_EXPECTED_INDICATORS[language_act])


# ---------------------------------------------------------------------------
# The coder
# ---------------------------------------------------------------------------


def _zero_values() -> dict[str, Any]:
    values: dict[str, Any] = {name: 0 for name in INDICATOR_NAMES}
    values["claim_strength_delta"] = None
    return values


def code_reply(
    reply_text: str,
    *,
    signals: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    language: str = "zh",
    lexicon: dict[str, Any] | None = None,
    prior_claim_strength: float | None = None,
) -> dict[str, Any]:
    """Code one reply text into the 15 indicator variables.

    Flags and counts are ``int``; ``claim_strength_delta`` is ``float | None``.
    ``_evidence`` holds the trace: one record per firing, per failed act, per
    explanatory note, and per predicted act from ``plan`` (see the module
    docstring for the note-prefix convention).

    ``plan`` is recorded, never consulted: coding stays blind to condition
    (``indicators.md:49-50``). ``signals`` is required for
    ``consonant_addition`` alone, and its absence is recorded rather than guessed.
    """
    active: dict[str, Any] = dict(lexicon) if lexicon else load_lexicon(language)
    text = reply_text if isinstance(reply_text, str) else ""
    evidence: list[dict[str, Any]] = []

    mask = _quote_mask(text, active)
    clause_spans = _split_with_offsets(text, language, mask)
    clauses = [clause for clause, _ in clause_spans]

    credited = _credit(_winning_spans(text, active, mask), active)
    hedge_hits = credited["hedges"]
    booster_hits = credited["boosters"]
    uncertainty_hits = credited["uncertainty_terms"]
    conflict_hits = credited["conflict_markers"]
    conditional_hits = credited["conditional_markers"]
    naming_hits = credited["condition_naming_cues"]
    quality_hits = credited["source_quality_cues"]
    discount_hits = credited["source_discount_cues"]
    verification_hits = credited["verification_cues"]
    addition_hits = credited["consonant_addition_cues"]
    minimiser_hits = credited["importance_minimisers"]
    concession_hits = credited["concession_markers"]
    stance_hits = credited["stance_change_markers"]
    softening_hits = credited["softening_cues"]
    acknowledgement_hits = credited["change_acknowledgement_cues"]
    reason_hits = credited["reason_step_markers"]

    counter_cue_hits = _cue_hits(text, _COUNTEREVIDENCE_CUES, mask, allow_quoted=True)
    support_cue_hits = _cue_hits(text, _SUPPORT_CUES, mask)
    opposing_hits = _cue_hits(text, _OPPOSING_CUES, mask)
    continuity_hits = _cue_hits(text, _CONTINUITY_CUES, mask)
    claim_hits = _cue_hits(text, _CLAIM_CUES, mask)
    claim_clauses = {_clause_index(clause_spans, hit[0]) for hit in claim_hits}

    evidence_terms = _evidence_terms(signals)

    # ---- lowered certainty: hedges minus boosters -------------------------
    values: dict[str, Any] = _zero_values()
    values["certainty_downgrade"] = len(hedge_hits) - len(booster_hits)
    for start, _end, span in hedge_hits:
        _record(evidence, clause_spans, "certainty_downgrade", start, span, "hedge counted against certainty")
    for start, _end, span in booster_hits:
        _record(evidence, clause_spans, "certainty_downgrade", start, span, "booster counted for certainty")

    # ---- uncertainty expressions ------------------------------------------
    values["uncertainty_term"] = len(uncertainty_hits)
    for start, _end, span in uncertainty_hits:
        _record(evidence, clause_spans, "uncertainty_term", start, span, "uncertainty expression")

    # ---- conflict awareness and two-sided weighing -------------------------
    overlap_hits = sorted(
        (index, sorted(_distinctive_terms(clause) & evidence_terms))
        for index, (clause, _offset) in enumerate(clause_spans)
        if evidence_terms and _distinctive_terms(clause) & evidence_terms
    )
    counterevidence_coded = bool(counter_cue_hits) or bool(overlap_hits)
    values["counterevidence_mention"] = 1 if counterevidence_coded else 0
    # When the cue set fires, the cue is the reason and is recorded. The
    # evidence-overlap test is recorded only when it is what carried the coding,
    # so a trace never cites a shared word such as 场景 as the reason for a value
    # that a named counter-evidence cue already established.
    if counter_cue_hits:
        for start, _end, span in counter_cue_hits:
            _record(evidence, clause_spans, "counterevidence_mention", start, span, "names the evidence that tells against the stance")
    else:
        for index, terms in overlap_hits:
            _record(
                evidence, clause_spans, "counterevidence_mention", clause_spans[index][1], terms[0],
                "shares a distinctive term with the supplied evidence and names no counter-evidence cue",
            )
    if not counterevidence_coded and signals:
        _record(evidence, clause_spans, "counterevidence_mention", None, "", "explains: the reply names none of the supplied evidence")

    values["support_mention"] = 1 if support_cue_hits else 0
    for start, _end, span in support_cue_hits:
        _record(evidence, clause_spans, "support_mention", start, span, "names a supporting consideration")

    conflict_value = 1 if conflict_hits else 0
    if not conflict_value and counterevidence_coded and opposing_hits:
        conflict_value = 1
    values["mark_conflict"] = conflict_value
    for start, _end, span in conflict_hits:
        _record(evidence, clause_spans, "mark_conflict", start, span, "conflict-aware marker")
    if not conflict_hits and conflict_value:
        _record(
            evidence,
            clause_spans,
            "mark_conflict",
            opposing_hits[0][0],
            opposing_hits[0][2],
            "conflict awareness inferred: the reply names a counter-evidence item and an opposing-direction cue, without the word 冲突",
        )
    if not conflict_value and text.strip():
        _record(evidence, clause_spans, "mark_conflict", None, "", "explains: no conflict-aware marker and no named counter-evidence item")

    # ---- 5. conditional acceptance ----------------------------------------
    conditional_by_clause: dict[int, list[tuple[int, int, str]]] = {}
    for hit in conditional_hits:
        conditional_by_clause.setdefault(_clause_index(clause_spans, hit[0]), []).append(hit)

    conditional_value = 0
    for index in sorted(conditional_by_clause):
        clause = clauses[index]
        marker = conditional_by_clause[index][0]
        generic = sorted(form for form in _GENERIC_CONDITION_FORMS if form in clause)
        naming_in_clause = [
            hit for hit in naming_hits if _clause_index(clause_spans, hit[0]) == index
        ]
        if generic:
            _record(
                evidence, clause_spans, "conditional_marker", marker[0], generic[0],
                "failed act: the conditional names no condition (indicators.md:64)",
            )
        elif not naming_in_clause:
            _record(
                evidence, clause_spans, "conditional_marker", marker[0], marker[2],
                "failed act: no condition is named in the conditional clause (indicators.md:64)",
            )
        elif not claim_hits:
            _record(
                evidence, clause_spans, "conditional_marker", marker[0], marker[2],
                "failed act: no claim of the agent's own is present, so the conditional is attached to nothing",
            )
        else:
            conditional_value = 1
            _record(
                evidence, clause_spans, "conditional_marker", marker[0], marker[2],
                f"conditional attached to the claim, naming a condition ({naming_in_clause[0][2]})",
            )
    values["conditional_marker"] = conditional_value
    if conditional_hits and not conditional_value:
        _record(evidence, clause_spans, "conditional_marker", None, "", "explains: every conditional in the reply is a failed act (see above)")

    # ---- explicit stance change -------------------------------------------
    values["explicit_stance_change"] = 1 if stance_hits else 0
    for start, _end, span in stance_hits:
        _record(evidence, clause_spans, "explicit_stance_change", start, span, "explicit from-to statement")

    # ---- reason chain ------------------------------------------------------
    reason_by_clause: dict[int, list[tuple[int, int, str]]] = {}
    for hit in reason_hits:
        reason_by_clause.setdefault(_clause_index(clause_spans, hit[0]), []).append(hit)
    values["reason_step_count"] = len(reason_by_clause)
    for step_number, index in enumerate(sorted(reason_by_clause), start=1):
        step = sorted(reason_by_clause[index])[0]
        _record(evidence, clause_spans, "reason_step_count", step[0], step[2], f"inferential step {step_number}")

    # ---- evidential weighting ---------------------------------------------
    values["source_quality_mention"] = 1 if quality_hits else 0
    for start, _end, span in quality_hits:
        _record(evidence, clause_spans, "source_quality_mention", start, span, "names a method, sample or provenance")

    # ---- verification path ------------------------------------------------
    values["verification_action"] = 1 if verification_hits else 0
    for start, _end, span in verification_hits:
        _record(evidence, clause_spans, "verification_action", start, span, "names a check a reader could perform")

    # ---- source discount --------------------------------------------------
    # Clause-scoped on purpose: naming a method-based reason in the same clause
    # makes the criticism source_quality_mention and *not* source_discount
    # (indicators.md:65).
    pointer_hits = _cue_hits(text, _SOURCE_POINTERS, mask)
    pointer_clauses = {_clause_index(clause_spans, hit[0]) for hit in pointer_hits}
    quality_clauses = {_clause_index(clause_spans, hit[0]) for hit in quality_hits}
    discount_value = 0
    for start, _end, span in discount_hits:
        index = _clause_index(clause_spans, start)
        if index in quality_clauses:
            _record(
                evidence, clause_spans, "source_discount", start, span,
                "not coded: the same clause names a method, sample or track record, so this is source_quality_mention (indicators.md:65)",
            )
            continue
        if index not in pointer_clauses:
            _record(
                evidence, clause_spans, "source_discount", start, span,
                "not coded: the clause names no source for the criticism to attach to",
            )
            continue
        discount_value = 1
        _record(evidence, clause_spans, "source_discount", start, span, "negative source claim without a method-based reason")
    values["source_discount"] = discount_value

    # ---- importance denial (order matters) --------------------------------
    events = sorted(
        [(start, "concession", span) for start, _end, span in concession_hits]
        + [(start, "minimiser", span) for start, _end, span in minimiser_hits]
    )
    importance_value = 0
    last_concession: tuple[int, str] | None = None
    for offset, kind, span in events:
        if kind == "concession":
            last_concession = (offset, span)
        elif last_concession is not None:
            importance_value = 1
            _record(
                evidence, clause_spans, "importance_denial", last_concession[0], last_concession[1],
                "concession, which the following minimiser answers",
            )
            _record(
                evidence, clause_spans, "importance_denial", offset, span,
                "relevance minimiser following a concession (indicators.md:40)",
            )
    values["importance_denial"] = importance_value
    if minimiser_hits and not importance_value:
        _record(
            evidence, clause_spans, "importance_denial", minimiser_hits[0][0], minimiser_hits[0][2],
            "not coded: no concession precedes a minimiser, and the rule requires that order",
        )

    # ---- consonant addition -----------------------------------------------
    values["consonant_addition"] = 0
    if signals is None:
        _record(
            evidence, clause_spans, "consonant_addition", None, "",
            "explains: no signals were supplied, so 'absent from the evidence' cannot be decided; coded 0",
        )
    else:
        exclusion_hits = [
            *uncertainty_hits, *quality_hits, *discount_hits, *minimiser_hits, *verification_hits,
            *conditional_hits, *conflict_hits, *opposing_hits,
        ]
        exclusion_clauses = {_clause_index(clause_spans, hit[0]) for hit in exclusion_hits}
        seen_terms: set[str] = set()
        for index, (clause, _offset) in enumerate(clause_spans):
            clause_terms = set(_distinctive_terms(clause))
            additions_here = [hit for hit in addition_hits if _clause_index(clause_spans, hit[0]) == index]
            continuity_here = [hit for hit in continuity_hits if _clause_index(clause_spans, hit[0]) == index]
            repeated = sorted(clause_terms & seen_terms)
            shared = sorted(clause_terms & evidence_terms)
            if additions_here:
                hit = additions_here[0]
                if index in exclusion_clauses:
                    _record(
                        evidence, clause_spans, "consonant_addition", hit[0], hit[2],
                        "not coded: the clause carries an epistemic or other-indicator cue rather than a supporting consideration",
                    )
                elif continuity_here:
                    _record(
                        evidence, clause_spans, "consonant_addition", hit[0], hit[2],
                        f"not coded: the clause marks the consideration as already standing ({continuity_here[0][2]})",
                    )
                elif shared:
                    _record(
                        evidence, clause_spans, "consonant_addition", hit[0], hit[2],
                        f"not coded: the consideration is already in the supplied evidence ({shared[0]})",
                    )
                elif repeated:
                    _record(
                        evidence, clause_spans, "consonant_addition", hit[0], hit[2],
                        f"not coded: the reply already used this consideration above ({repeated[0]})",
                    )
                else:
                    values["consonant_addition"] = 1
                    _record(
                        evidence, clause_spans, "consonant_addition", hit[0], hit[2],
                        "new supporting consideration absent from the supplied evidence",
                    )
            seen_terms |= clause_terms

    # ---- silent drift ------------------------------------------------------
    # The indicator is coded from the text: a claim-weakening cue sitting on a
    # clause that carries the agent's own claim. The rated delta is reported
    # beside it but never triggers it on its own, because the rating below is an
    # uncalibrated placeholder and a negative delta from it would otherwise code
    # silent drift in a reply that restates its claim verbatim.
    delta: float | None = None
    claim_scoped_hedges = _scoped(hedge_hits, clause_spans, claim_clauses)
    claim_scoped_boosters = _scoped(booster_hits, clause_spans, claim_clauses)
    softening_in_claim = _scoped(softening_hits, clause_spans, claim_clauses)
    current_strength = _rate_from_parts(
        bool(claim_hits),
        claim_scoped_hedges,
        claim_scoped_boosters,
        len(conditional_by_clause),
        softening_in_claim,
    )
    if prior_claim_strength is None:
        _record(
            evidence, clause_spans, "claim_strength_delta", None, "",
            "explains: prior_claim_strength was not supplied; indicators.md:51-53 codes the delta on the before/after pair, so none is returned",
        )
    elif current_strength is None:
        _record(
            evidence, clause_spans, "claim_strength_delta", None, "",
            "explains: the reply carries no rateable claim, so no delta is returned",
        )
    else:
        delta = round(current_strength - float(prior_claim_strength), 4)
        _record(
            evidence, clause_spans, "claim_strength_delta", None, "",
            f"explains: rated current claim {current_strength} minus prior {float(prior_claim_strength)}, by the "
            "uncalibrated commitment-cue heuristic in rate_claim_strength",
        )
    values["claim_strength_delta"] = delta

    weakening_hits = sorted(
        hit for hit in [*softening_hits, *hedge_hits] if _clause_index(clause_spans, hit[0]) in claim_clauses
    )
    if weakening_hits:
        acknowledged = bool(acknowledgement_hits) or bool(stance_hits)
        values["unacknowledged_softening"] = 0 if acknowledged else 1
        for start, _end, span in weakening_hits:
            _record(evidence, clause_spans, "unacknowledged_softening", start, span, "claim weakened here")
        if acknowledged:
            first = sorted([*acknowledgement_hits, *stance_hits])[0]
            _record(
                evidence, clause_spans, "unacknowledged_softening", first[0], first[2],
                "not coded: the reply acknowledges the change, so this is not silent drift",
            )
    else:
        values["unacknowledged_softening"] = 0
        if delta is not None and delta < 0:
            _record(
                evidence, clause_spans, "unacknowledged_softening", None, "",
                f"not coded: the rated claim strength falls by {abs(delta):.4f}, but no weakening cue sits on a "
                "claim-bearing clause, so the wording of the claim is not weaker and this is not coded as drift",
            )

    # ---- predictions from the plan, recorded and never consulted -----------
    acts: list[str] = []
    if isinstance(plan, dict):
        raw_acts = plan.get("language_acts")
        if isinstance(raw_acts, list):
            acts = [act for act in raw_acts if isinstance(act, str)]
    for act in acts:
        expectations = _EXPECTED_INDICATORS.get(act, {})
        if expectations:
            for name in INDICATOR_NAMES:
                predicate = expectations.get(name)
                if predicate:
                    _record(
                        evidence, clause_spans, name, None, act,
                        f"expected_act: {act} predicts {name}={predicate}; a prediction, it does not affect coding",
                    )
        else:
            _record(
                evidence, clause_spans, "_act", None, act,
                f"expected_act: {act} carries no machine-readable expectation in indicators.md",
            )

    result: dict[str, Any] = {name: values[name] for name in INDICATOR_NAMES}
    result["_evidence"] = evidence
    return result
