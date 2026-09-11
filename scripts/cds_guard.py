"""The stealth guard: the cheap front half of detection.

Why this module exists
----------------------
v0.3.0 was switched on by a command and then ran the *whole* loop on every turn:
rate a full signal packet, detect, evaluate, and print three cards. That is the
right shape for an experiment and the wrong shape for a conversation. A component
that costs a full packet and three cards on every ordinary turn is not a component
a user leaves on; it is one they turn off.

The guard fixes the cost without changing the measurement. It splits detection in
two:

* **Screening (this module).** One sparse packet, one arithmetic pass, one
  decision. When the decision is ``silent`` the guard prints one line, emits no
  card, and the turn proceeds as an ordinary turn. Nothing about the skill is
  visible to the user and nothing downstream runs.
* **Escalation (unchanged v0.3 pipeline).** Only when the decision is ``surface``
  *and* the user consents does the full packet, the evaluator, the response plan
  and the three cards run.

What this module deliberately does *not* do
-------------------------------------------
It does not rate anything. The host model rates; the guard decides. Every number
below is a function of the packet and the config, so the same packet always
produces the same decision, and no decision can be traced to a model's mood.

It also does not re-implement the arithmetic. ``build_detection`` computes the
tension index, the volition gate and both channel levels exactly as it does for a
full packet, and the guard reads that result. There is one index, one gate and one
set of thresholds in this repository, and this module adds only the *screening
policy* on top: how clear a conflict has to be before a user is interrupted.

Why the surface bar is stricter than the alert bar
--------------------------------------------------
``thresholds.alert`` answers "is this conflict real enough to record?". The guard
answers a different question: "is this conflict clear enough to spend the user's
attention on?" Those are not the same bar, and using the recording bar for the
interruption would make the skill nag about every marginal event — which is how a
transparency feature becomes an annoyance feature. ``guard.surface_threshold`` is
therefore validated at load time to sit at or above every alert threshold.
"""

from __future__ import annotations

import re
from typing import Any

from cds_config import canonical_hash, skill_version
from cds_index import build_detection, claims_of

GUARD_VERSION = "cds-guard-0.1"

#: Decision values. ``surface`` means "show the user a card and ask"; ``silent``
#: means "record it and behave exactly as if the skill were not installed".
SURFACE = "surface"
SILENT = "silent"

#: Why the guard stayed silent. Recorded rather than inferred, so a log analysis
#: can tell "nothing clashed" from "something clashed and the policy held it back".
R_INERT = "arm_inert"
R_NO_CONFLICT = "no_conflict_perceived"
R_GATED = "gated_not_dissonance"
R_BELOW_ALERT = "below_alert_threshold"
R_BELOW_SURFACE = "below_surface_threshold"
R_WEAK_OPPOSITION = "opposition_below_floor"
R_COOLDOWN = "cooldown_active"
R_DISMISSED = "dismissed_by_user"
R_BUDGET = "surface_budget_exhausted"

#: Why the guard surfaced. Recorded alongside the decision so that an interrupted
#: user can always be told which rule interrupted them.
SURFACE_ASK = "policy_ask_user"
SURFACE_AUTO = "policy_auto_escalate"
SURFACE_LOG_ONLY = "arm_withholds_the_user_step"

_WHITESPACE = re.compile(r"\s+")


def _norm(text: Any) -> str:
    """Normalise a claim for identity comparison, never for display."""
    if not isinstance(text, str):
        return ""
    return _WHITESPACE.sub(" ", text).strip().casefold()


def conflict_key(signals: dict[str, Any]) -> str:
    """A stable identity for "the same conflict", used by dismissal memory.

    The key is over the *pair of claims* rather than over the event id. Event ids
    include the turn, so they change on every restatement and could not answer the
    question the dismissal memory has to answer: "is this the same thing the user
    already told me to drop?". Two differently-worded restatements of one conflict
    still differ, which is the honest limitation of a lexical key; novelty, not the
    key, is what lets a genuinely new turn on the same topic back through.
    """
    claims = claims_of(signals)
    material = {
        "type": (signals.get("relation") or {}).get("type"),
        "a": _norm((claims.get("a") or {}).get("text")),
        "b": _norm((claims.get("b") or {}).get("text")),
    }
    return "cds_key_" + canonical_hash(material).split(":", 1)[1][:12]


def guard_policy(config: dict[str, Any]) -> str:
    return str(config.get("guard", {}).get("policy", "ask"))


def _surface_policy(config: dict[str, Any], mode: str) -> tuple[str, str]:
    """The guard's action for a conflict that clears every bar.

    Returns ``(next_action, reason)``. The arm overrides the policy because the
    arms exist to withhold stages: a ``detect_only`` run that asked the user for
    permission to evaluate would be asking for something that arm may never do, and
    a ``placebo`` run has to keep the *same cadence* as ``full`` or the placebo
    stops being a cadence-matched control.
    """
    if mode == "placebo":
        return "await_user_decision", SURFACE_ASK
    if mode == "detect_only":
        return "log_only", SURFACE_LOG_ONLY
    policy = guard_policy(config)
    if policy == "log_only":
        return "log_only", SURFACE_LOG_ONLY
    if policy == "auto":
        return "auto_evaluate", SURFACE_AUTO
    return "await_user_decision", SURFACE_ASK


def run_guard(
    signals: dict[str, Any],
    config: dict[str, Any],
    *,
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Screen one sparse packet and decide whether to interrupt the user.

    ``history`` carries the session facts the decision needs and that the packet
    cannot know: which conflicts the user already dismissed, how recently the guard
    last surfaced, and how many times it has surfaced at all. It is a plain dict so
    that the decision is testable without a state file, and absent so that a
    stateless run still works.
    """
    mode = config["skill"]["mode"]
    guard_config = config.get("guard") or {}
    history = history or {}

    detection = build_detection(signals, config)
    tension_result = detection["tension_result"]
    event = detection["conflict_event"]

    tension = float(tension_result["tension"])
    level = tension_result["level"]
    channel = tension_result["channel"]
    conflict_type = event["conflict_type"]
    gated = bool((event.get("gate") or {}).get("applied"))
    opposition = float(event["terms"]["opposition"]["raw"])
    novelty = float(event.get("novelty", 0.0))

    surface_threshold = float(guard_config.get("surface_threshold", config["thresholds"]["alert"]))
    opposition_floor = float(guard_config.get("min_opposition", 0.0))
    key = conflict_key(signals)
    claims = event.get("claims") or claims_of(signals)

    reasons: list[str] = []
    decision = SILENT
    next_action = "log_only"

    # Ordered screening. Each condition is necessary; the first failure is the
    # recorded reason, so the log says *why* an event was held back rather than
    # only that it was.
    if mode == "off" or not guard_config.get("enabled", True):
        reasons.append(R_INERT)
    elif conflict_type == "none":
        reasons.append(R_NO_CONFLICT)
    elif gated and channel != "indeterminacy":
        # A conflict against a stance the agent did not choose is not dissonance.
        # The gate already capped it below every alert threshold, so reaching here
        # means the cap itself was not the binding constraint; the labelling rule
        # is, and the guard does not ask a user about a construct it just declined.
        reasons.append(R_GATED)
    elif level == "silent":
        reasons.append(R_BELOW_ALERT)
    elif tension < surface_threshold:
        reasons.append(R_BELOW_SURFACE)
    elif opposition < opposition_floor:
        reasons.append(R_WEAK_OPPOSITION)
    else:
        decision = SURFACE
        next_action, reason = _surface_policy(config, mode)
        reasons.append(reason)

    # Session-level inhibitors. These are checked only after the packet has cleared
    # every content bar, so a held-back event is always a clear conflict and never
    # a marginal one, and the log distinguishes the two.
    if decision == SURFACE:
        dismissed = {
            entry.get("conflict_key") or entry.get("key")
            for entry in (history.get("dismissed") or [])
        }
        resurface = float(guard_config.get("resurface_novelty", 1.0))
        if guard_config.get("dismiss_memory", True) and key in dismissed and novelty < resurface:
            decision = SILENT
            next_action = "log_only"
            reasons[:] = [R_DISMISSED]

    if decision == SURFACE:
        last_turn = history.get("last_surface_turn")
        current_turn = history.get("current_turn")
        cooldown = int(guard_config.get("cooldown_turns", 0) or 0)
        if (
            cooldown > 0
            and isinstance(last_turn, int)
            and isinstance(current_turn, int)
            and 0 <= current_turn - last_turn <= cooldown
        ):
            decision = SILENT
            next_action = "log_only"
            reasons[:] = [R_COOLDOWN]

    if decision == SURFACE:
        budget = int(guard_config.get("max_surfaces_per_run", 0) or 0)
        surfaces_before = int(history.get("surfaces_count", 0) or 0)
        if budget > 0 and surfaces_before >= budget:
            decision = SILENT
            next_action = "log_only"
            reasons[:] = [R_BUDGET]

    asks_user = decision == SURFACE and next_action == "await_user_decision"

    return {
        "schema_version": skill_version(),
        "skill_version": skill_version(),
        "guard_version": GUARD_VERSION,
        "config_hash": canonical_hash(config),
        "run_id": signals.get("run_id"),
        "turn_id": signals.get("turn_id"),
        "decision": decision,
        "reasons": reasons,
        "policy": guard_policy(config),
        "next_action": next_action if decision == SURFACE else "log_only",
        "asks_user": asks_user,
        "mode": mode,
        "placebo": mode == "placebo",
        "surface_threshold": surface_threshold,
        "min_opposition": opposition_floor,
        "conflict_key": key,
        "conflict_type": conflict_type,
        "channel": channel,
        "level": level,
        "gated": gated,
        "tension": tension,
        "opposition": opposition,
        "novelty": novelty,
        "claims": claims,
        "detection": detection,
        "history": {
            "current_turn": history.get("current_turn"),
            "surfaces_count": int(history.get("surfaces_count", 0) or 0),
            "last_surface_turn": history.get("last_surface_turn"),
            "dismissed_before": key
            in {
                entry.get("conflict_key") or entry.get("key")
                for entry in (history.get("dismissed") or [])
            },
        },
    }


def escalation_hint(result: dict[str, Any]) -> str:
    """One line telling the host model what to do with this decision.

    Kept in the module rather than in prose documentation because it is the
    interface between the engine and the harness: the model reads this line and
    nothing else when the guard is silent, and it is the only place the two-step
    packet upgrade is spelled out at runtime.
    """
    if result["decision"] == SILENT:
        return "CDS_GUARD silent"
    if result["next_action"] == "log_only":
        return "CDS_GUARD surface (log only; this arm never evaluates)"
    if result["next_action"] == "auto_evaluate":
        return "CDS_GUARD surface -> evaluate now (no user decision required in this arm)"
    return "CDS_GUARD surface -> show the card and wait for the user decision"
