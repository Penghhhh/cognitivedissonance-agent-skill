"""The one-line screen: bands in, sparse packet out.

Why this module exists
----------------------
v0.4.0 screened with a *sparse JSON packet*: nine decimal ratings, an id for each
claim, written to a file and passed by path. It was already much cheaper than the
full packet, and it was still the wrong shape for something that runs on every
turn with a conflict candidate. The host model spent its budget on ceremony -
quoting keys, inventing ids, writing a file - and the arithmetic it fed was the
same nine numbers every time.

v0.5.0 keeps the numbers and drops the ceremony. The model now rates **six
coarse bands** and passes them inline::

    python scripts/cds.py guard --type evidence_vs_stance \\
      --screen "opp=high,commit=high,vol=high,self=high,spec=high,nov=high" \\
      --stance "X 在该场景下是可靠的" \\
      --anchor "第 2 轮我说：X 在该场景下是可靠的" \\
      --evidence "新研究显示 X 在主要使用场景下存在重大缺陷"

No file, no JSON, no ids, no quotes around numbers. Banding costs resolution and
that cost is deliberate: this is a **gate**, not a measurement. The screening bar
is coarse on purpose (see ``cds_guard``), a band cannot be mistaken for a precise
reading, and the precise rating is still made - once - on the escalation path,
where it is recorded and analysed.

The anchor is required here, at parse time, for every conflict type that carries a
stance. The engine refuses such a packet at the guard as well; requiring it here as
well means the host model cannot even construct the packet that produced v0.4.0's
worst failure, in which a first turn with no prior assertion anywhere produced a
card announcing that "what I said earlier" had been contradicted.
"""

from __future__ import annotations

from typing import Any, Sequence

#: Band name -> 0-1 value. ``mid`` sits exactly on the codebook's "moderate"
#: anchor, and the spread is wide enough that a banded packet and a decimal packet
#: agree on the level for every case that is not itself a boundary case.
BANDS: dict[str, float] = {
    "none": 0.00,
    "low": 0.30,
    "mid": 0.60,
    "high": 0.85,
}

#: Single-letter and numeric spellings, so a model that is being terse has a legal
#: way to be terse rather than a reason to guess at the parser.
_BAND_ALIASES: dict[str, str] = {
    "n": "none", "0": "none", "zero": "none", "none": "none",
    "l": "low", "1": "low", "low": "low",
    "m": "mid", "2": "mid", "medium": "mid", "moderate": "mid", "mid": "mid",
    "h": "high", "3": "high", "high": "high",
}

#: Field aliases. The left-hand side is what a model actually types; the right-hand
#: side is the packet key it becomes.
_FIELD_ALIASES: dict[str, str] = {
    "opp": "opposition", "opposition": "opposition",
    "spec": "specificity", "specificity": "specificity",
    "commit": "commitment", "commitment": "commitment",
    "public": "public_commitment", "public_commitment": "public_commitment",
    "vol": "volition", "volition": "volition",
    "self": "self_relevance", "self_relevance": "self_relevance",
    "nov": "novelty", "novelty": "novelty",
    "press": "user_pressure", "pressure": "user_pressure", "user_pressure": "user_pressure",
    "unc": "evidence_conflict_unresolved",
    "unresolved": "evidence_conflict_unresolved",
    "evidence_conflict_unresolved": "evidence_conflict_unresolved",
}

#: The six terms the tension index consumes. All six are required for any conflict
#: type: an omitted term would be silently defaulted, and a silently defaulted term
#: is a decision the engine made without being told it was making one.
CORE_FIELDS = ("opposition", "commitment", "volition", "self_relevance", "specificity", "novelty")

_TYPE_ALIASES: dict[str, str] = {
    "none": "none",
    "evs": "evidence_vs_stance",
    "evidence_vs_stance": "evidence_vs_stance",
    "eve": "evidence_vs_evidence",
    "evidence_vs_evidence": "evidence_vs_evidence",
    "uhs": "user_hint_vs_stance",
    "user_hint_vs_stance": "user_hint_vs_stance",
    "mvc": "memory_vs_current",
    "memory_vs_current": "memory_vs_current",
}

#: Conflict types whose packet must point at a span. ``evidence_vs_evidence`` has no
#: stance to anchor and ``none`` has nothing to say.
TYPES_NEEDING_ANCHOR = ("evidence_vs_stance", "user_hint_vs_stance", "memory_vs_current")

NORMATIVE_PRIOR = "normative_prior"


class ScreenError(ValueError):
    """A screen string or flag set that cannot be turned into an honest packet."""


def parse_type(raw: str | None) -> str:
    """Resolve a type spelling, long or short."""
    if raw is None or not str(raw).strip():
        return "none"
    key = str(raw).strip().lower()
    if key not in _TYPE_ALIASES:
        raise ScreenError(
            f"unknown --type {raw!r}. Use one of: "
            + ", ".join(sorted(set(_TYPE_ALIASES.values())))
            + " (short forms: evs, eve, uhs, mvc, none)"
        )
    return _TYPE_ALIASES[key]


def parse_band(token: str) -> float:
    """Resolve one band token. Raw decimals are passed through."""
    text = token.strip().lower()
    if text in _BAND_ALIASES:
        return BANDS[_BAND_ALIASES[text]]
    try:
        value = float(text)
    except ValueError:
        raise ScreenError(
            f"unknown band {token!r}. Use none/low/mid/high (= {BANDS['none']}/{BANDS['low']}/"
            f"{BANDS['mid']}/{BANDS['high']}) or a decimal between 0 and 1."
        ) from None
    if not 0.0 <= value <= 1.0:
        raise ScreenError(f"band {token!r} is outside 0-1.")
    return value


def parse_screen(spec: str | None) -> dict[str, float]:
    """Parse ``"opp=high, commit=high; vol=h"`` into packet fields.

    Separators are commas, semicolons and whitespace, all equivalent, because the
    one thing this parser must not do is fail on a punctuation choice. A leading
    ``type=`` pair is accepted and ignored here: it is resolved by ``parse_type``,
    and accepting it in both places means the model cannot get the two spellings out
    of step.
    """
    fields: dict[str, float] = {}
    if not spec:
        return fields
    normalised = spec.replace(",", " ").replace(";", " ").replace("|", " ")
    for chunk in normalised.split():
        if "=" not in chunk:
            raise ScreenError(
                f"screen item {chunk!r} is not key=value. Example: "
                '"opp=high,commit=high,vol=high,self=high,spec=high,nov=high"'
            )
        key, _, value = chunk.partition("=")
        key = key.strip().lower()
        if key in ("type", "relation", "relation_type"):
            continue
        if key not in _FIELD_ALIASES:
            raise ScreenError(
                f"unknown screen field {key!r}. Known fields: "
                + ", ".join(sorted(set(_FIELD_ALIASES)))
            )
        canonical = _FIELD_ALIASES[key]
        if canonical in fields:
            raise ScreenError(f"screen field {canonical!r} was given twice.")
        fields[canonical] = parse_band(value)

    missing = [name for name in CORE_FIELDS if name not in fields]
    if missing:
        raise ScreenError(
            "the screen is missing "
            + ", ".join(missing)
            + ". All six index terms are required; the engine will not default a "
            "rating you did not give it. Example: "
            '"opp=high,commit=high,vol=high,self=high,spec=high,nov=high"'
        )
    return fields


def build_sparse_packet(
    *,
    conflict_type: str,
    screen: str | None = None,
    stance_claim: str | None = None,
    anchor: str | None = None,
    evidence_claims: Sequence[str] = (),
    source: str | None = None,
    normative_basis: str | None = None,
    annotator: str | None = None,
    run_id: str | None = None,
    turn_id: int | None = None,
) -> dict[str, Any]:
    """Assemble the sparse packet ``cds.py guard`` screens.

    The shape is the same one ``references/prompts/triage.md`` documents, so a
    packet built here and a packet written by hand are indistinguishable
    downstream, and a hand-written packet can be extended into the full one after
    the user consents without the engine knowing which route it came in by.
    """
    resolved_type = parse_type(conflict_type)

    if resolved_type == "none":
        return {
            "run_id": run_id or "",
            "turn_id": turn_id if turn_id is not None else 0,
            "annotator": annotator or "model",
            "relation": {"type": "none", "opposition": 0.0, "specificity": 0.0},
            "evidence": [],
            "user_pressure": 0.0,
            "evidence_conflict_unresolved": 0.0,
        }

    fields = parse_screen(screen)
    # `public_commitment` is not an index term - it moves the cost of changing
    # position downstream - so it defaults to `commitment` rather than being asked
    # for twice. Leaving it out of the screen entirely is the honest default: the
    # two are separate variables and the escalation packet rates it properly.
    fields.setdefault("public_commitment", fields["commitment"])
    fields.setdefault("user_pressure", 0.0)
    fields.setdefault("evidence_conflict_unresolved", 0.0)

    claims = [str(item).strip() for item in evidence_claims if str(item).strip()]
    if not claims:
        raise ScreenError(
            "--evidence is required: a conflict needs the thing it is in conflict with, "
            "quoted or closely paraphrased from the context."
        )

    packet: dict[str, Any] = {
        "run_id": run_id or "",
        "turn_id": turn_id if turn_id is not None else 0,
        "annotator": annotator or "model",
        "relation": {
            "type": resolved_type,
            "opposition": fields["opposition"],
            "specificity": fields["specificity"],
        },
        "evidence": [
            {"id": f"e{index + 1}", "claim": claim, "novelty": fields["novelty"]}
            for index, claim in enumerate(claims)
        ],
        "user_pressure": fields["user_pressure"],
        "evidence_conflict_unresolved": fields["evidence_conflict_unresolved"],
    }

    if resolved_type == "evidence_vs_evidence":
        # No stance, and inventing one would let a decision problem masquerade as
        # dissonance. This is the same rule the full packet enforces.
        return packet

    stance_claim = (stance_claim or "").strip()
    if not stance_claim:
        raise ScreenError(
            f"--stance is required for {resolved_type}: name the position the new "
            "information is in conflict with, in one sentence, in the words the "
            "context actually used."
        )

    resolved_source = (source or "").strip() or "prior_conversation"
    anchor = (anchor or "").strip()
    normative = resolved_source == NORMATIVE_PRIOR

    if resolved_type in TYPES_NEEDING_ANCHOR and resolved_source != "system_prompt" and not anchor:
        raise ScreenError(
            "--anchor is required: quote the span in this conversation that the stance "
            "is read off (an earlier message of your own, the user's words, a memory "
            "entry or a tool output). Without it there is no evidence the position was "
            "ever held, and the engine will not raise a conflict about a position "
            "nobody stated. If the position is a mainstream value norm rather than "
            f"something from the conversation, pass --source {NORMATIVE_PRIOR} and "
            "--norm instead."
        )

    if normative and not (normative_basis or "").strip():
        raise ScreenError(
            f"--norm is required with --source {NORMATIVE_PRIOR}: name the mainstream "
            "norm in one short clause, e.g. 「不得对平民实施暴力」."
        )

    packet["stance"] = {
        "id": "s1",
        "claim": stance_claim,
        "source": resolved_source,
        "commitment": fields["commitment"],
        "public_commitment": fields["public_commitment"],
        "volition": fields["volition"],
        "self_relevance": fields["self_relevance"],
        "anchor": anchor,
    }
    if normative:
        packet["stance"]["normative_basis"] = normative_basis.strip()
    return packet
