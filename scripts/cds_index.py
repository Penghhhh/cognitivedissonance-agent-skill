"""The CDS Tension Index.

What this module computes, precisely
------------------------------------
``T = clip( w_opposition*opposition
          + w_commitment*commitment
          + w_volition_self*volition_self
          + w_specificity*specificity
          + w_novelty*novelty, 0, 1)``

subject to the dissonance gate below, where ``volition_self`` is the product of
the free-choice rating and the self-relevance rating.

What it is not
--------------
``T`` is not a measurement of an internal state and this module never claims one.
It is an index constructed over five ratings that a perceiver (model or human)
supplied, and its only defensible interpretation is ordinal: higher means the
conflict is more directly opposed, more load-bearing, more freely chosen, more
checkable and more new. The name "tension" is kept from v0.1 for continuity.

Two deliberate departures from v0.1
-----------------------------------
1. **User pressure is not a term.** In v0.1 it carried weight 0.15, which meant a
   user who repeated a demand could raise the index and force a re-evaluation.
   That is a sycophancy channel built into the arousal mechanism, and it
   contradicted the same document's stated goal of resisting sycophancy. Pressure
   is now logged as a moderator and acts only on strategy selection, downstream.
2. **Repetition is inverted into novelty.** v0.1 added 0.10 for repetition, so
   restating a known objection scored higher than raising a new one. Novelty now
   means new information, which is what should raise attention.

The dissonance gate
-------------------
Dissonance theory requires a freely chosen, self-relevant commitment (Festinger &
Carlsmith, 1959). A conflict against a position the agent was *assigned* is a
conflict, not dissonance. So when ``volition_self`` falls below
``index.gates.volition_floor``, the index is capped at
``index.gates.non_dissonant_cap`` and the cap is validated at load time to sit
strictly below every alert threshold. The gate therefore cannot be quietly
defeated by a config edit.

The indeterminacy channel
-------------------------
``evidence_vs_evidence`` conflicts have no stance, so the gate correctly refuses
to call them dissonance. They are still worth reporting, so they travel on a
separate, ungated channel and every card they produce says "indeterminacy"
rather than "dissonance".
"""

from __future__ import annotations

import math
from typing import Any

from cds_config import canonical_hash, skill_version

_LEVEL_ORDER = {"silent": 0, "alert": 1, "high": 2}

_STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "kp_opposition": "新证据与既有立场方向相反",
        "kp_credibility": "证据来源可信度较高",
        "kp_commitment": "既有立场承诺度较高",
        "kp_volition": "该立场由智能体自主选择，而非被指派",
        "kp_novelty": "该信息为新出现的信息，并非重复提及",
        "kp_specificity": "冲突具体且可核查",
        "kp_pressure": "检测到用户施压，可能影响后续策略选择",
        "unc_independence": "证据独立性尚未确认",
        "unc_consistency": "证据之间一致性偏低",
        "unc_unresolved": "证据之间互相冲突，修正方向尚未确定",
        "unc_perception": "感知置信度偏低，评级可能不稳定",
        "unc_no_anchor": "部分评级缺少原文锚点",
        "unc_no_stance": "未找到智能体自身立场，本次按不确定性问题处理",
        "gate_detail": "自主选择信号低于门槛，该冲突不计入失调，指数已封顶",
    },
    "en": {
        "kp_opposition": "The new element points against the existing stance",
        "kp_credibility": "The source of the evidence is comparatively credible",
        "kp_commitment": "The existing stance carries substantial commitment",
        "kp_volition": "The stance was chosen by the agent rather than assigned to it",
        "kp_novelty": "The information is new rather than a restatement",
        "kp_specificity": "The contradiction is concrete and checkable",
        "kp_pressure": "User pressure detected; it may shape the strategy chosen",
        "unc_independence": "Evidence independence is not established",
        "unc_consistency": "The evidence items agree with each other only weakly",
        "unc_unresolved": "The evidence contradicts itself, so no direction of revision is determined",
        "unc_perception": "Perception confidence is low, so these ratings may be unstable",
        "unc_no_anchor": "Some ratings carry no verbatim anchor",
        "unc_no_stance": "No stance of the agent's own was found; treated as indeterminacy",
        "gate_detail": "Free-choice signal is below the floor, so this conflict is not counted as dissonance and the index is capped",
    },
}


def _t(language: str, key: str) -> str:
    table = _STRINGS.get(language) or _STRINGS["zh"]
    return table[key]


def carrying_evidence(signals: dict[str, Any]) -> list[dict[str, Any]]:
    """Evidence items that actually carry the contradiction."""
    items = signals.get("evidence") or []
    return [item for item in items if item.get("carries_conflict", True)]


def claims_of(signals: dict[str, Any]) -> dict[str, Any]:
    """Name the two elements that clash: ``{"a": {...}, "b": {...}}``.

    The user-facing card rests on this. A reader told "conflict detected, index
    0.71" has been handed a number and still does not know what the conflict *was*;
    a reader told "you said X, this says not-X" has been handed the thing itself.
    Before v0.4.0 the detection record carried a stance claim and a list of
    evidence **ids** but never the evidence's own claim text, so a card could not
    print the second half of a contradiction even in principle.

    Roles come from the conflict type, which is an enum, rather than from an
    evidence ``source`` string, which is free text: a card that guessed the role
    from a source name would mislabel the first packet whose source was spelled
    unusually. A ``None`` side means the packet did not name that element, and the
    card omits the line rather than inventing a placeholder for it.
    """
    relation_type = (signals.get("relation") or {}).get("type") or "none"
    stance = signals.get("stance") or {}
    members = carrying_evidence(signals)

    def side(role: str, text: Any, **extra: Any) -> dict[str, Any] | None:
        if not isinstance(text, str) or not text.strip():
            return None
        return {"role": role, "text": text.strip(), **extra}

    if relation_type == "none":
        return {"a": None, "b": None}

    if relation_type == "evidence_vs_evidence":
        first = side("evidence", members[0].get("claim"), evidence_id=members[0].get("id")) if members else None
        second = (
            side("evidence", members[1].get("claim"), evidence_id=members[1].get("id"))
            if len(members) > 1
            else None
        )
        return {"a": first, "b": second}

    if relation_type == "memory_vs_current":
        a_role, b_role = "memory", "current"
    elif relation_type == "user_hint_vs_stance":
        a_role, b_role = "stance", "user_hint"
    else:  # evidence_vs_stance
        a_role, b_role = "stance", "evidence"

    member = members[0] if members else {}
    return {
        "a": side(a_role, stance.get("claim"), source=stance.get("source")),
        "b": side(b_role, member.get("claim"), evidence_id=member.get("id")),
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def volition_self_value(stance: dict[str, Any] | None) -> tuple[float, float, float]:
    """Return ``(volition, self_relevance, product)``.

    The product is the index rule because the two conditions are conjunctive: a
    freely chosen but impersonal position is not self-relevant, and a personal but
    assigned position was not freely chosen. Neither substitution is defensible,
    so neither is offered. ``scripts/sensitivity.py`` recomputes with the mean to
    show what the alternative would have changed.
    """
    if not stance:
        return 0.0, 0.0, 0.0
    volition = float(stance.get("volition", 0.0))
    self_relevance = float(stance.get("self_relevance", 0.0))
    return volition, self_relevance, volition * self_relevance


def resolve_thresholds(config: dict[str, Any], conflict_type: str) -> tuple[float, float, float, str]:
    """Return ``(low, alert, high, source)`` honouring a per-type override."""
    thresholds = config["thresholds"]
    low, high = thresholds["low"], thresholds["high"]
    override = (config.get("thresholds_by_type") or {}).get(conflict_type)
    if override is None:
        return low, thresholds["alert"], high, "global"
    return low, float(override), high, f"thresholds_by_type:{conflict_type}"


def build_terms(signals: dict[str, Any], config: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Rate-by-rate decomposition of the index. Every contribution is named."""
    relation = signals.get("relation") or {}
    stance = signals.get("stance")
    weights = config["index"]["weights"]

    _, _, volition_self = volition_self_value(stance)
    commitment = float((stance or {}).get("commitment", 0.0))
    novelty_values = [float(item.get("novelty", 0.0)) for item in carrying_evidence(signals)]
    novelty = max(novelty_values) if novelty_values else 0.0

    raw_terms = {
        "opposition": float(relation.get("opposition", 0.0)),
        "commitment": commitment,
        "volition_self": volition_self,
        "specificity": float(relation.get("specificity", 0.0)),
        "novelty": novelty,
    }
    return {
        name: {
            "raw": raw_value,
            "weight": float(weights[name]),
            "contribution": raw_value * float(weights[name]),
        }
        for name, raw_value in raw_terms.items()
    }


def build_event_id(signals: dict[str, Any]) -> str:
    """Deterministic event id: identical signals yield an identical id.

    Timestamps are excluded on purpose so that replaying a stored packet in a
    later session reproduces the event rather than minting a new one.
    """
    material = {
        "run_id": signals.get("run_id"),
        "turn_id": signals.get("turn_id"),
        "type": (signals.get("relation") or {}).get("type"),
        "stance_id": (signals.get("stance") or {}).get("id"),
        "evidence_ids": sorted(item.get("id", "") for item in carrying_evidence(signals)),
    }
    return "cds_evt_" + canonical_hash(material).split(":", 1)[1][:12]


def _key_points(signals: dict[str, Any], terms: dict[str, dict[str, float]], config: dict[str, Any], language: str) -> list[str]:
    points: list[str] = []
    members = carrying_evidence(signals)
    stance = signals.get("stance") or {}

    if terms["opposition"]["raw"] >= 0.60:
        points.append(_t(language, "kp_opposition"))
    if terms["specificity"]["raw"] >= 0.60:
        points.append(_t(language, "kp_specificity"))

    credibility = _mean([float(item.get("credibility", 0.0)) for item in members if "credibility" in item])
    if credibility is not None and credibility >= 0.60:
        points.append(_t(language, "kp_credibility"))

    if terms["commitment"]["raw"] >= 0.60:
        points.append(_t(language, "kp_commitment"))

    floor = config["index"]["gates"]["volition_floor"]
    if terms["volition_self"]["raw"] >= floor and stance:
        points.append(_t(language, "kp_volition"))

    novelty_values = [float(item.get("novelty", 0.0)) for item in members if "novelty" in item]
    if novelty_values and max(novelty_values) >= 0.60:
        points.append(_t(language, "kp_novelty"))

    if float(signals.get("user_pressure", 0.0)) >= 0.60:
        points.append(_t(language, "kp_pressure"))

    return points


def _uncertainties(signals: dict[str, Any], config: dict[str, Any], language: str) -> list[str]:
    notes: list[str] = []
    members = carrying_evidence(signals)
    stance = signals.get("stance")

    independence = _mean([float(item.get("independence", 0.0)) for item in members if "independence" in item])
    if independence is not None and len(members) > 1 and independence < 0.50:
        notes.append(_t(language, "unc_independence"))

    consistency = _mean([float(item.get("consistency", 0.0)) for item in members if "consistency" in item])
    if consistency is not None and consistency < 0.50:
        notes.append(_t(language, "unc_consistency"))

    if float(signals.get("evidence_conflict_unresolved", 0.0)) >= 0.40:
        notes.append(_t(language, "unc_unresolved"))

    perception = signals.get("perception") or {}
    if perception.get("confidence") is not None and float(perception["confidence"]) < 0.50:
        notes.append(_t(language, "unc_perception"))

    rated = [item for item in members if any(key in item for key in ("relevance", "credibility", "recency"))]
    if rated and any(not item.get("quote") for item in rated):
        notes.append(_t(language, "unc_no_anchor"))

    _, _, volition_self = volition_self_value(stance)
    if stance is None or volition_self < config["index"]["gates"]["volition_floor"]:
        if (signals.get("relation") or {}).get("type") in ("evidence_vs_evidence", "none"):
            notes.append(_t(language, "unc_no_stance"))

    return notes


def build_detection(signals: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Produce the full ``DetectionResult`` for one signal packet."""
    language = config["skill"]["language"]
    mode = config["skill"]["mode"]
    interaction = config["skill"]["interaction"]

    relation = signals.get("relation") or {}
    conflict_type = relation.get("type", "none")
    stance = signals.get("stance")
    members = carrying_evidence(signals)

    terms = build_terms(signals, config)
    # fsum, not sum: the level below is assigned by a bare ``>=`` against a
    # threshold, so the accumulation algorithm must not be part of the answer.
    # CPython 3.12 replaced ``sum``'s naive loop with Neumaier compensated
    # summation, and a term vector that is exactly a threshold in decimal can land
    # one ulp either side of it: the same corpus therefore routed ``s43`` to
    # ``alert`` on 3.9 and to ``high`` on 3.12. ``fsum`` is exactly rounded and is
    # the same function on every version, which is what the reproducibility claim
    # in this module needs.
    raw_index = math.fsum(term["contribution"] for term in terms.values())

    volition, self_relevance, volition_self = volition_self_value(stance)
    gates = config["index"]["gates"]

    gate: dict[str, Any] = {"applied": False, "rule": "none", "floor": None, "cap": None, "detail": None}
    tension = min(max(raw_index, 0.0), 1.0)

    if conflict_type != "none" and volition_self < gates["volition_floor"]:
        gate = {
            "applied": True,
            "rule": "volition_floor",
            "floor": gates["volition_floor"],
            "cap": gates["non_dissonant_cap"],
            "detail": _t(language, "gate_detail"),
        }
        tension = min(tension, gates["non_dissonant_cap"])

    low, alert, high, threshold_source = resolve_thresholds(config, conflict_type)
    if conflict_type == "none":
        index_level = "silent"
    elif tension >= high:
        index_level = "high"
    elif tension >= alert:
        index_level = "alert"
    else:
        index_level = "silent"

    unresolved = float(signals.get("evidence_conflict_unresolved", 0.0))
    indeterminacy_config = config["channels"]["indeterminacy"]
    indeterminacy_fires = bool(indeterminacy_config["enabled"]) and unresolved >= indeterminacy_config["alert"]
    if not indeterminacy_fires:
        indeterminacy_level = "silent"
    elif unresolved >= indeterminacy_config["high"]:
        indeterminacy_level = "high"
    else:
        indeterminacy_level = "alert"

    dissonance_fires = bool(config["channels"]["dissonance"]["enabled"]) and index_level in ("alert", "high")
    if dissonance_fires:
        channel = "dissonance"
    elif indeterminacy_fires:
        channel = "indeterminacy"
    else:
        channel = "none"

    level = max((index_level, indeterminacy_level), key=lambda name: _LEVEL_ORDER[name])

    if mode in ("off", "placebo"):
        next_action = "skip"
    elif mode == "detect_only":
        next_action = "log_only"
    elif level == "silent":
        next_action = "log_only"
    elif interaction == "ambient":
        next_action = "auto_evaluate"
    else:
        next_action = "await_user_decision"

    novelty_values = [float(item.get("novelty", 0.0)) for item in members if "novelty" in item]

    conflict_event = {
        "event_id": build_event_id(signals),
        "conflict_type": conflict_type,
        "rationale": relation.get("rationale"),
        "stance": None
        if not stance
        else {
            "id": stance.get("id"),
            "claim": stance.get("claim"),
            "confidence": stance.get("confidence"),
            "commitment": float(stance.get("commitment", 0.0)),
            "public_commitment": float(stance.get("public_commitment", 0.0)),
            "source": stance.get("source"),
        },
        "evidence_ids": [item.get("id", "") for item in members],
        "claims": claims_of(signals),
        "terms": terms,
        "volition_detail": {
            "volition": volition,
            "self_relevance": self_relevance,
            "rule": "product",
            "value": volition_self,
        },
        "user_pressure": float(signals.get("user_pressure", 0.0)),
        "evidence_conflict_unresolved": unresolved,
        "novelty": max(novelty_values) if novelty_values else 0.0,
        "raw_index": raw_index,
        "gate": gate,
    }

    tension_result = {
        "index_version": config["index"]["index_version"],
        "tension": tension,
        "level": level,
        "channel": channel,
        "channel_levels": {"dissonance": index_level, "indeterminacy": indeterminacy_level},
        "indeterminacy": unresolved,
        "threshold_low": low,
        "threshold_alert": alert,
        "threshold_high": high,
        "threshold_source": threshold_source,
        "key_points": _key_points(signals, terms, config, language),
        "uncertainty": _uncertainties(signals, config, language),
        "next_action": next_action,
    }

    consistency_config = config["consistency_gate"]
    severity = float((signals.get("consistency_gate") or {}).get("internal_contradiction", 0.0))
    consistency_result = {
        "flagged": bool(consistency_config["enabled"]) and severity >= consistency_config["severity_alert"],
        "severity": severity,
        "route": consistency_config["routes_to"] if consistency_config["enabled"] else "off",
    }

    return {
        "schema_version": skill_version(),
        "skill_version": skill_version(),
        "index_version": config["index"]["index_version"],
        "config_hash": canonical_hash(config),
        "run_id": signals.get("run_id"),
        "turn_id": signals.get("turn_id"),
        "detected_at": signals.get("detected_at"),
        "placebo": mode == "placebo",
        "conflict_event": conflict_event,
        "tension_result": tension_result,
        "consistency_gate_result": consistency_result,
    }
