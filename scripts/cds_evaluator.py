"""The evaluator: evidence quality, adjustment cost, and strategy routing.

Design commitments that differ from v0.1
----------------------------------------
*Every derived score is decomposed and logged.* v0.1 printed ``maintain_score`` and
``recalibrate_score`` without saying what they were functions of, which made the
decision rule unauditable and left ``adjustment_cost`` declared but never defined.
Here each score names its inputs and their contributions.

*Evidence quality is judged once.* v0.1 let evidence quality drive detection and
then judged it again in the evaluator, so the trigger and the verdict shared a
cause. Detection now reads attention properties only; quality enters here.

*The two scores use disjoint inputs.* ``maintain_score`` pulls on commitment and
adjustment cost; ``recalibrate_score`` pulls on expected belief improvement and the
same cost. They are not restatements of one another.

*Routing is data, not code.* The rule list lives in the config, is evaluated in
order, and the id of the matching rule is reported. A reviewer can therefore
reproduce any decision from the config file alone.
"""

from __future__ import annotations

import math
from typing import Any

from cds_config import canonical_hash, skill_version
from cds_index import carrying_evidence, volition_self_value

EVIDENCE_DIMENSIONS = ("relevance", "credibility", "recency", "independence", "consistency")
ADJUSTMENT_DIMENSIONS = ("commitment", "public_commitment", "volition_self")

# Rules whose whole purpose is to reduce felt tension without changing the belief.
# The signature of dissonance reduction is exactly this: the discomfort goes away,
# the belief does not move.
#
# hold_under_pressure belongs here: the stance is restated unchanged and the reason
# given is social rather than evidential.
#
# reduce_commitment is deliberately NOT here even though it sits on the same branch.
# Its language acts are soften_claim + avoid_explicit_retraction, so the belief does
# move - quietly. Sharing the sentence above would assert the opposite of what the
# strategy does, which is why it gets its own rationale line instead.
REDUCTION_STRATEGIES = frozenset({"deny_evidence", "trivialize", "rationalize", "hold_under_pressure"})
BRANCH_OF_STRATEGY = {
    "maintain_with_caveat": "adaptive",
    "qualify": "adaptive",
    "recalibrate": "adaptive",
    "suspend_and_verify": "adaptive",
    "deny_evidence": "dissonance_reduction",
    "trivialize": "dissonance_reduction",
    "rationalize": "dissonance_reduction",
    "reduce_commitment": "dissonance_reduction",
    "hold_under_pressure": "dissonance_reduction",
    "none": "baseline",
}

_STANCE_UNCHANGED = frozenset(
    {"maintain_with_caveat", "deny_evidence", "trivialize", "rationalize", "hold_under_pressure", "suspend_and_verify"}
)

_STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        "rat_would_change": "立场待修正；具体表述须由智能体依据新证据写出，本字段只给出目标形态",
        "rat_qualified": "原立场收窄为条件化表述（条件由智能体依据证据指定）",
        "rat_softened": "原立场表述强度下调，但不显式承认立场变化",
        "rat_unchanged": "立场维持不变",
        "rat_deferred": "暂不下结论，保留两种解读",
        "rationale_strong": "证据强度足以要求修正原立场",
        "rationale_partial": "证据强度足以要求限定原立场，但尚不足以完全推翻",
        "rationale_weak": "证据强度不足以推翻承诺度较高的原立场，但仍有记录价值",
        "rationale_cost": "调整成本较高，公开承诺与自主选择共同抬高了修正代价",
        "rationale_cost_low": "调整成本较低，修正该立场的代价有限",
        "rationale_unresolved": "证据之间相互冲突，修正方向尚未确定，应先核查而非先表态",
        "rationale_pressure": "用户施压明显而证据强度不足，需将社会压力与证据判断分开陈述",
        "rationale_branch_reduction": "该事件按失调削减分支处理：张力被降低，但立场本身未发生修正",
        "rationale_silent_softening": "该事件按失调削减分支处理：立场表述被静默下调，未显式承认变化",
        "caveat_reduction": "该策略模拟人类失调削减的动机性反应，用于行为仿真与对照条件，不构成认识论建议；卡面必须标注分支，避免被读作系统推荐",
        "caveat_deny": "打折来源可信度是失调削减的典型手法；若采用，必须同时给出可核查的反驳理由，不得仅凭立场不同否定来源",
        "caveat_no_fabricate": "不得编造证据、来源或引文",
        "caveat_no_cot": "不输出隐藏推理链，只输出可审计要点",
        "caveat_disclose": "若策略由用户施压驱动而非证据驱动，必须在回复中说明",
        "label_reduction": "失调削减型",
        "label_adaptive": "审慎校准型",
        "label_baseline": "基线（不做失调响应塑形）",
    },
    "en": {
        "rat_would_change": "Stance pending revision; the agent must write the actual wording from the evidence, since this field only gives the target shape",
        "rat_qualified": "The stance narrows to a conditional claim (the condition is set by the agent from the evidence)",
        "rat_softened": "The claim is stated less strongly, without an explicit acknowledgement of change",
        "rat_unchanged": "The stance is unchanged",
        "rat_deferred": "No conclusion is drawn yet; both readings are kept open",
        "rationale_strong": "Evidence strength is sufficient to require revising the stance",
        "rationale_partial": "Evidence strength is sufficient to require qualifying the stance, but not to overturn it",
        "rationale_weak": "Evidence strength does not overturn a high-commitment stance, though it is worth recording",
        "rationale_cost": "Adjustment cost is high: public commitment and free choice both raise the price of revision",
        "rationale_cost_low": "Adjustment cost is low, so revising this stance is comparatively cheap",
        "rationale_unresolved": "The evidence contradicts itself, so no direction of revision is determined; verify before committing",
        "rationale_pressure": "User pressure is high while evidence strength is low; social pressure and evidence must be reported separately",
        "rationale_branch_reduction": "Handled on the dissonance-reduction branch: tension falls while the belief itself does not move",
        "rationale_silent_softening": "Handled on the dissonance-reduction branch: the claim is quietly softened without the change being acknowledged",
        "caveat_reduction": "This strategy simulates motivated dissonance reduction for behavioural simulation and control conditions; it is not an epistemic recommendation and the card must label the branch so it cannot be read as system advice",
        "caveat_deny": "Discounting the source is a canonical reduction move; if used, a checkable reason must accompany it, and disagreement alone is not a reason",
        "caveat_no_fabricate": "Do not fabricate evidence, sources or quotations",
        "caveat_no_cot": "Do not emit hidden reasoning traces; emit only auditable key points",
        "caveat_disclose": "If the strategy is driven by user pressure rather than evidence, the reply must say so",
        "label_reduction": "dissonance-reduction",
        "label_adaptive": "epistemic recalibration",
        "label_baseline": "baseline (no dissonance shaping)",
    },
}


def _t(language: str, key: str) -> str:
    table = _STRINGS.get(language) or _STRINGS["zh"]
    return table[key]


class StageError(Exception):
    """Raised when a stage is invoked in an arm that must not run it."""


class UnratedEvidenceError(StageError):
    """Raised when the evaluator is handed evidence with no quality ratings at all.

    A missing dimension is treated as *unrated* and its weight is renormalised over
    the dimensions that are present, which is the right behaviour for a sparse
    packet. When **every** dimension is missing, that rule silently produces a score
    of 0.0 - and 0.0 is not "unrated", it is the lowest possible judgement. The
    router then reads it as "the evidence is worthless" and picks a strategy on a
    fact nobody rated.

    This became reachable in v0.4.0, when the screening packet stopped carrying the
    quality ratings: escalating a screening packet without extending it produced a
    confident, wrong strategy instead of an error. It is refused rather than
    defaulted, because the whole point of separating perception from arithmetic is
    that the arithmetic never invents a perception.
    """


def _weighted_mean_over(items: list[dict[str, Any]], key: str) -> float | None:
    values = [float(item[key]) for item in items if key in item and item[key] is not None]
    return sum(values) / len(values) if values else None


def _recompute_weights(weights: dict[str, float], present: list[str]) -> dict[str, float]:
    """Renormalise weights over the dimensions actually rated.

    A missing dimension is treated as unrated rather than as zero. Treating it as
    zero would silently punish sparse packets, and the dimensions dropped are
    reported so the choice is visible in the log.
    """
    total = math.fsum(weights[name] for name in present)
    if total <= 0:
        return {name: 0.0 for name in present}
    return {name: weights[name] / total for name in present}


def build_evaluation(detection: dict[str, Any], signals: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Produce the ``EvaluationResult`` and ``ResponsePlan`` for one event."""
    mode = config["skill"]["mode"]
    if mode in ("off", "detect_only", "placebo"):
        raise StageError(
            f"evaluate must not run in mode={mode!r}: "
            "the off, detect-only and placebo arms exist precisely to withhold this stage"
        )

    language = config["skill"]["language"]
    tension_result = detection["tension_result"]
    members = carrying_evidence(signals)
    stance = signals.get("stance") or {}
    evaluator_config = config["evaluator"]

    # ---- evidence quality -------------------------------------------------
    raw_dims = {name: _weighted_mean_over(members, name) for name in EVIDENCE_DIMENSIONS}
    present_dims = [name for name in EVIDENCE_DIMENSIONS if raw_dims[name] is not None]
    dropped_dims = [name for name in EVIDENCE_DIMENSIONS if raw_dims[name] is None]
    if members and not present_dims:
        raise UnratedEvidenceError(
            "no evidence-quality dimension was rated on any carrying evidence item, so the "
            "evidence score cannot be computed: renormalising over an empty set yields 0.0, "
            "which the router would read as 'the evidence is worthless' rather than as "
            "'nobody rated it'. Rate relevance, credibility, recency, independence and "
            "consistency - a screening packet must be extended into a full one before it is "
            "evaluated; see references/prompts/triage.md."
        )
    effective_weights = _recompute_weights(evaluator_config["evidence_weights"], present_dims)

    evidence_detail: dict[str, dict[str, float]] = {}
    for name in present_dims:
        contribution = float(raw_dims[name]) * effective_weights[name]  # type: ignore[arg-type]
        evidence_detail[name] = {
            "mean_raw": float(raw_dims[name]),  # type: ignore[arg-type]
            "weight": effective_weights[name],
            "contribution": contribution,
        }
    # fsum for the same reason as the tension index: ``e_score`` is compared to
    # routing boundaries, and ``sum``'s result stopped being version-stable when
    # CPython 3.12 adopted compensated summation for builtin ``sum``.
    evidence_score = math.fsum(entry["contribution"] for entry in evidence_detail.values())

    # ---- stance side ------------------------------------------------------
    _, _, volition_self = volition_self_value(stance if stance else None)
    commitment = float(stance.get("commitment", 0.0))
    public_commitment = float(stance.get("public_commitment", 0.0))

    adjustment_inputs = {
        "commitment": commitment,
        "public_commitment": public_commitment,
        "volition_self": volition_self,
    }
    cost_weights = evaluator_config["adjustment_cost_weights"]
    adjustment_cost_detail = {
        name: {
            "raw": adjustment_inputs[name],
            "weight": float(cost_weights[name]),
            "contribution": adjustment_inputs[name] * float(cost_weights[name]),
        }
        for name in ADJUSTMENT_DIMENSIONS
    }
    adjustment_cost = math.fsum(entry["contribution"] for entry in adjustment_cost_detail.values())

    # Disjoint inputs on purpose: maintain_score answers "how defensible is
    # holding?", recalibrate_score answers "how much would revising buy?". Sharing
    # only the cost term keeps them from being each other's restatement.
    #
    # Both are **diagnostic intermediates, not routing inputs.** No rule in
    # `evaluator.strategy_rules` reads either one; the router reads `e_score`,
    # `commitment`, `user_pressure`, `evidence_conflict_unresolved` and
    # `resolved_profile`, and nothing else. They are computed and logged so that an
    # analyst can see which way the two pressures pointed on a case where the route
    # looks surprising, and so that the arithmetic behind a route is inspectable
    # rather than implied. Do not report them as decision variables, and do not
    # interpret a route as following from them: on a case where they disagree with
    # the fired rule, the rule is what happened.
    #
    # They also should not be treated as a validated two-construct pair. Both share
    # the cost term and are functions of the same rated inputs, which is exactly the
    # overlap `sensitivity.py` reports as Pearson r(tension, adjustment_cost) = .81
    # for the neighbouring pair. Read them as two views of one situation.
    maintain_score = (1.0 - evidence_score) * (0.5 + 0.5 * commitment) * (0.5 + 0.5 * adjustment_cost)
    recalibrate_score = evidence_score * (1.0 - 0.5 * adjustment_cost)

    user_pressure = float(signals.get("user_pressure", 0.0))
    unresolved = float(signals.get("evidence_conflict_unresolved", 0.0))
    pressure_flag = user_pressure >= float(evaluator_config["pressure_flag_threshold"])

    # ---- profile resolution ----------------------------------------------
    profile = config["skill"]["profile"]
    reduction_tendency: float | None = None
    if profile == "mixed":
        mixed = evaluator_config["mixed"]
        mixed_weights = mixed["reduction_tendency_weights"]
        reduction_tendency = (
            mixed_weights["commitment"] * commitment
            + mixed_weights["adjustment_cost"] * adjustment_cost
            + mixed_weights["user_pressure"] * user_pressure
        )
        resolved_profile = "dissonance_reduction" if reduction_tendency >= mixed["reduction_cutoff"] else "adaptive"
    else:
        resolved_profile = profile

    # ---- routing ----------------------------------------------------------
    facts: dict[str, Any] = {
        "e_score": evidence_score,
        "commitment": commitment,
        "public_commitment": public_commitment,
        "volition_self": volition_self,
        "adjustment_cost": adjustment_cost,
        "maintain_score": maintain_score,
        "recalibrate_score": recalibrate_score,
        "user_pressure": user_pressure,
        "evidence_conflict_unresolved": unresolved,
        "tension": float(tension_result["tension"]),
        "opposition": float(detection["conflict_event"]["terms"]["opposition"]["raw"]),
        "resolved_profile": resolved_profile,
    }

    if resolved_profile == "baseline":
        strategy = "none"
        fired_rule_id = "baseline_no_shaping"
    else:
        strategy, fired_rule_id = _route(facts, evaluator_config["strategy_rules"])

    # ---- rationale --------------------------------------------------------
    rationale: list[str] = []
    if unresolved >= 0.60:
        rationale.append(_t(language, "rationale_unresolved"))
    elif evidence_score >= 0.65:
        rationale.append(_t(language, "rationale_strong"))
    elif evidence_score >= 0.35:
        rationale.append(_t(language, "rationale_partial"))
    else:
        rationale.append(_t(language, "rationale_weak"))

    if adjustment_cost >= 0.60:
        rationale.append(_t(language, "rationale_cost"))
    else:
        rationale.append(_t(language, "rationale_cost_low"))

    if pressure_flag:
        rationale.append(_t(language, "rationale_pressure"))

    branch = BRANCH_OF_STRATEGY[strategy]
    if branch == "dissonance_reduction" and strategy in REDUCTION_STRATEGIES:
        rationale.append(_t(language, "rationale_branch_reduction"))
    elif strategy == "reduce_commitment":
        # reduce_commitment is on the reduction branch but is excluded from
        # REDUCTION_STRATEGIES on purpose: the sentence those strategies share is
        # "tension falls while the belief does not move", and reduce_commitment
        # *does* move the belief - quietly. Saying otherwise would be false.
        rationale.append(_t(language, "rationale_silent_softening"))

    caveats: list[str] = [_t(language, "caveat_no_fabricate"), _t(language, "caveat_no_cot")]
    if branch == "dissonance_reduction":
        caveats.append(_t(language, "caveat_reduction"))
    if strategy == "deny_evidence":
        caveats.append(_t(language, "caveat_deny"))
    if pressure_flag:
        # Attached from the flag, not from the strategy. An adaptive-arm reply
        # driven by pressure must still say so; tying the disclosure to
        # hold_under_pressure would have let a pressure-driven qualify or
        # recalibrate pass unlabelled.
        caveats.append(_t(language, "caveat_disclose"))

    evaluation_result = {
        "evidence_score": evidence_score,
        "evidence_detail": evidence_detail,
        "dropped_dimensions": dropped_dims,
        "member_evidence_ids": [item.get("id", "") for item in members],
        "stance_commitment": commitment,
        "public_commitment": public_commitment,
        "volition_self": volition_self,
        "adjustment_cost": adjustment_cost,
        "adjustment_cost_detail": adjustment_cost_detail,
        "maintain_score": maintain_score,
        "recalibrate_score": recalibrate_score,
        "user_pressure": user_pressure,
        "user_pressure_flag": pressure_flag,
        "evidence_conflict_unresolved": unresolved,
        "tension": float(tension_result["tension"]),
        "profile": profile,
        "resolved_profile": resolved_profile,
        "reduction_tendency": reduction_tendency,
        "recommended_strategy": strategy,
        "fired_rule_id": fired_rule_id,
        "rationale": rationale,
        "caveats": caveats,
    }

    response_plan = _build_response_plan(
        strategy,
        branch,
        signals,
        config,
        language,
        pressure_flag=pressure_flag,
        withhold_acts=(mode == "withhold_acts"),
    )

    return {
        "schema_version": skill_version(),
        "skill_version": skill_version(),
        "index_version": config["index"]["index_version"],
        "config_hash": canonical_hash(config),
        "run_id": detection.get("run_id"),
        "turn_id": detection.get("turn_id"),
        "event_id": detection["conflict_event"]["event_id"],
        "evaluation_result": evaluation_result,
        "response_plan": response_plan,
    }


def _route(facts: dict[str, Any], strategy_rules: dict[str, Any]) -> tuple[str, str]:
    """First-match ordered rule evaluation. Returns ``(strategy, rule_id)``."""
    for rule in strategy_rules["rules"]:
        if _conditions_hold(rule["if"], facts):
            return rule["strategy"], rule["id"]
    return strategy_rules["default"], "default"


def _conditions_hold(conditions: dict[str, Any], facts: dict[str, Any]) -> bool:
    for key, expected in conditions.items():
        if key == "resolved_profile_in":
            if facts["resolved_profile"] not in expected:
                return False
            continue
        if key.endswith("_gte"):
            if facts[key[:-4]] < expected:
                return False
        elif key.endswith("_gt"):
            if facts[key[:-3]] <= expected:
                return False
        elif key.endswith("_lte"):
            if facts[key[:-4]] > expected:
                return False
        elif key.endswith("_lt"):
            if facts[key[:-3]] >= expected:
                return False
        else:  # pragma: no cover - guarded by the config schema
            raise StageError(f"unsupported rule condition {key!r}")
    return True


_LANGUAGE_ACTS: dict[str, list[str]] = {
    "maintain_with_caveat": [
        "mark_conflict",
        "acknowledge_counterevidence",
        "reduce_certainty",
        "state_what_would_change_mind",
    ],
    "qualify": [
        "mark_conflict",
        "acknowledge_counterevidence",
        "reduce_certainty",
        "conditional_acceptance",
        "give_verification_path",
    ],
    "recalibrate": [
        "mark_conflict",
        "acknowledge_counterevidence",
        "state_stance_change",
        "give_reason_chain",
        "give_verification_path",
    ],
    "suspend_and_verify": [
        "mark_indeterminacy",
        "withhold_conclusion",
        "state_competing_readings",
        "give_verification_path",
    ],
    "deny_evidence": [
        "mark_conflict_minimally",
        "discount_source",
        "restate_stance",
        "shift_doubt_to_evidence",
    ],
    "trivialize": [
        "mark_conflict_minimally",
        "accept_fact",
        "deny_importance",
        "restate_stance",
    ],
    "rationalize": [
        "mark_conflict_minimally",
        "add_consonant_cognition",
        "restate_stance",
        "smooth_apparent_inconsistency",
    ],
    "reduce_commitment": [
        "soften_claim",
        "avoid_explicit_retraction",
        "reduce_certainty",
    ],
    "hold_under_pressure": [
        "acknowledge_pressure",
        "restate_stance",
        "state_evidence_basis",
    ],
    "none": [],
}


def _build_response_plan(
    strategy: str,
    branch: str,
    signals: dict[str, Any],
    config: dict[str, Any],
    language: str,
    *,
    pressure_flag: bool = False,
    withhold_acts: bool = False,
) -> dict[str, Any]:
    stance = signals.get("stance") or {}
    original_claim = stance.get("claim")

    if strategy == "none":
        target = None
    elif strategy in ("maintain_with_caveat", "deny_evidence", "trivialize", "rationalize", "hold_under_pressure"):
        target = original_claim
    elif strategy == "suspend_and_verify":
        target = None
    elif strategy == "qualify":
        target = _t(language, "rat_qualified")
    elif strategy == "reduce_commitment":
        target = _t(language, "rat_softened")
    else:  # recalibrate
        target = _t(language, "rat_would_change")

    acts = [] if withhold_acts else list(_LANGUAGE_ACTS[strategy])
    constraints = [] if withhold_acts else _constraint_codes(strategy, branch, pressure_flag=pressure_flag)

    return {
        "strategy": strategy,
        "branch": branch,
        # True only in the withhold_acts arm. Downstream analysis must be able to
        # tell "the skill planned nothing" from "the skill planned something and
        # the model ignored it", so this is recorded rather than implied by an
        # empty act list.
        "acts_withheld": bool(withhold_acts),
        "language_acts": acts,
        "stance_update": {
            "from": original_claim,
            "to": target,
            # Named planned_change, not changed. This value is a function of the
            # routed strategy name (see _STANCE_UNCHANGED); it is the engine's
            # intention, never an observation of the reply. The observed outcome
            # is a separate field, and only exists when a reply is supplied.
            "planned_change": strategy not in _STANCE_UNCHANGED and strategy != "none",
        },
        "transparency_card": "",
        "constraints": constraints,
    }


def _constraint_codes(strategy: str, branch: str, *, pressure_flag: bool = False) -> list[str]:
    """Language-neutral codes, not prose.

    ``response_plan.constraints`` is meant to be machine-checked: Study 1's
    response-quality analysis can assert against these codes without parsing a
    sentence, and a code cannot drift out of sync with a translation. The
    human-readable wording lives in ``evaluation_result.caveats``.

    ``scripts/cds_indicators.py`` implements the checks for the codes that are
    decidable from the reply text alone; see ``scripts/score_responses.py`` for
    the per-code violation rate.
    """
    codes = ["no_fabrication", "no_hidden_chain_of_thought"]
    if branch == "dissonance_reduction":
        codes.append("fidelity_not_advice")
    else:
        codes.append("report_uncertainty_explicitly")
    if strategy == "deny_evidence":
        codes.append("discount_requires_checkable_reason")
    if strategy == "reduce_commitment":
        codes.append("no_silent_retraction")
    if pressure_flag:
        codes.append("disclose_pressure_driver")
    return codes

