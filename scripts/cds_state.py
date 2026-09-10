"""The event state machine.

v0.1's machine had four defects that this module fixes, each of which would have
produced unusable data in a study:

1. **It could deadlock.** ``AWAITING_USER`` had no timeout, so a participant who
   answered something other than the five magic words left the skill parked
   forever and every later turn silently unmonitored. There is now an
   ``await_timeout_turns`` deadline after which the event is logged as
   "no decision" and monitoring resumes.
2. **It had no queue.** Detection produced a single implicit event, so a turn with
   three conflicts, or a conflict arriving while another was being evaluated, had
   no defined behaviour. Events are now a bounded set with a declared policy for
   overflow.
3. **``SUSPENDED`` had no exit condition.** "稍后" now expires, resumes on a
   sufficiently novel new detection, or resumes on command.
4. **``RESOLVED``/``UNRESOLVED`` were drawn as states but never as decisions.**
   They are now an ``outcome`` property of an event, and the machine returns to
   MONITORING, which is what the v0.1 diagram actually did.

The state file is JSON on disk so that a run survives a process restart, which is
a prerequisite for the long sessions Study 2 will need.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_VERSION = "0.2.0"

STATES = (
    "IDLE",
    "MONITORING",
    "DETECTED",
    "AWAITING_USER",
    "EVALUATING",
    "RESPONDING",
    "SUSPENDED",
)

# Open = detected but not yet through the loop. 'awaiting' and 'suspended' are
# also open, and are tracked through the machine state rather than by status.
OPEN_STATUSES = frozenset({"open", "awaiting", "suspended"})

COMMAND_SYNONYMS: dict[str, tuple[str, ...]] = {
    "process": ("处理", "评估", "process", "evaluate", "eval", "yes", "好", "可以"),
    "ignore": ("忽略", "ignore", "dismiss", "skip", "不用"),
    "later": ("稍后", "later", "defer", "suspend", "等会"),
    "details": ("详情", "details", "detail", "展开"),
    "resume": ("恢复", "继续", "resume", "continue"),
    "off": ("关闭cds", "关闭", "off", "disable", "stop"),
    "on": ("开启cds", "开启", "on", "enable", "start"),
    "status": ("状态", "status"),
    "reset": ("重置", "reset"),
}

_MESSAGES: dict[str, dict[str, str]] = {
    "zh": {
        "process": "进入评估阶段。",
        "ignore": "已记录并忽略该事件，回到监测。",
        "later": "已暂缓该事件，回到监测；收到足够新的证据或回复“处理”时恢复。",
        "details": "展开结构化细节。",
        "resume": "已恢复暂缓的事件。",
        "off": "CDS 已关闭，回到 IDLE。",
        "on": "CDS 已开启，进入 MONITORING。",
        "reset": "状态已重置。",
        "status": "当前状态如下。",
        "unknown": "无法识别的指令，状态未改变。可用指令：处理 / 忽略 / 稍后 / 详情 / 恢复 / 关闭 CDS / 开启 CDS / 状态。",
        "no_active": "当前没有待处理的事件，指令未生效。",
        "timeout": "等待超时：本轮未收到决定，事件已记录为未决，监测继续（不会阻塞后续回合）。",
        "expired": "暂缓超时：事件已过期并记录，监测继续。",
        "resumed_by_novelty": "出现足够新的证据，暂缓事件已恢复。",
    },
    "en": {
        "process": "Entering evaluation.",
        "ignore": "Event recorded and ignored; back to monitoring.",
        "later": "Event suspended; monitoring resumes and it returns on sufficiently novel evidence or on 'process'.",
        "details": "Expanding structured detail.",
        "resume": "Suspended event resumed.",
        "off": "CDS disabled; back to IDLE.",
        "on": "CDS enabled; entering MONITORING.",
        "reset": "State reset.",
        "status": "Current state follows.",
        "unknown": "Unrecognised command; state unchanged. Available: process / ignore / later / details / resume / off / on / status.",
        "no_active": "No pending event, so the command had no effect.",
        "timeout": "Await timed out: no decision this turn, the event is logged as undecided and monitoring continues without blocking later turns.",
        "expired": "Suspend expired: the event is logged as expired and monitoring continues.",
        "resumed_by_novelty": "Sufficiently novel evidence arrived; the suspended event has resumed.",
    },
}


def _m(language: str, key: str) -> str:
    return (_MESSAGES.get(language) or _MESSAGES["zh"])[key]


class StateError(Exception):
    """Raised on an illegal state transition."""


def normalise_command(text: str) -> str | None:
    """Map a user utterance onto a command, tolerating surrounding punctuation."""
    if not text:
        return None
    cleaned = text.strip().lower()
    for command, synonyms in COMMAND_SYNONYMS.items():
        for synonym in synonyms:
            if cleaned == synonym or cleaned.startswith(synonym):
                return command
    return None


class StateMachine:
    """Bounded, timeout-protected event machine with an on-disk footprint."""

    def __init__(self, config: dict[str, Any], run_id: str, path: Path | None = None) -> None:
        self.config = config
        self.path = Path(path) if path else None
        self.language = config["skill"]["language"]
        self.loaded = False
        self.data: dict[str, Any] = {
            "state_version": STATE_VERSION,
            "run_id": run_id,
            "state": "IDLE" if not config["skill"]["enabled"] else "MONITORING",
            "turn": 0,
            "await_deadline_turn": None,
            "active_event_id": None,
            "events": [],
            "history": [],
            "dropped": [],
        }

    # ---- persistence ------------------------------------------------------

    @classmethod
    def load(
        cls,
        config: dict[str, Any],
        run_id: str | None,
        path: str | Path | None,
    ) -> "StateMachine":
        """Load a stored run, or start one.

        ``run_id=None`` means "continue whatever this file holds", which is what
        the multi-call interactive loop needs: each CLI invocation is a separate
        process, so a minted-fresh id every time would silently discard the state
        written by the previous call and the user's decision would never reach the
        evaluator. Passing an explicit ``run_id`` that differs from the stored one
        is an intentional override and starts clean.
        """
        machine = cls(config, run_id or "unset", Path(path) if path else None)
        if machine.path and machine.path.exists():
            stored = json.loads(machine.path.read_text(encoding="utf-8-sig"))
            if run_id is None or stored.get("run_id") == run_id:
                machine.data = stored
                machine.loaded = True
        return machine

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- helpers ----------------------------------------------------------

    @property
    def state(self) -> str:
        return self.data["state"]

    def _set_state(self, target: str, reason: str) -> None:
        if target not in STATES:
            raise StateError(f"unknown state {target!r}")
        current = self.data["state"]
        if current != target:
            self.data["history"].append({"turn": self.data["turn"], "from": current, "to": target, "reason": reason})
            self.data["state"] = target

    def _find(self, event_id: str | None) -> dict[str, Any] | None:
        for event in self.data["events"]:
            if event["event_id"] == event_id:
                return event
        return None

    @property
    def active_event(self) -> dict[str, Any] | None:
        return self._find(self.data["active_event_id"])

    def open_events(self) -> list[dict[str, Any]]:
        return [event for event in self.data["events"] if event["status"] in OPEN_STATUSES]

    def _age(self) -> None:
        for event in self.data["events"]:
            event["age_turns"] = self.data["turn"] - event["turn"]

    # ---- lifecycle --------------------------------------------------------

    def advance_turn(self) -> dict[str, Any]:
        """Called once at the start of every agent turn. Never raises on staleness."""
        self.data["turn"] += 1
        self._age()
        events: list[str] = []

        if self.state == "AWAITING_USER":
            deadline = self.data.get("await_deadline_turn")
            if deadline is not None and self.data["turn"] > deadline:
                active = self.active_event
                if active:
                    active["status"] = "logged"
                    active["outcome"] = "no_decision"
                    events.append(_m(self.language, "timeout"))
                self.data["active_event_id"] = None
                self.data["await_deadline_turn"] = None
                self._set_state("MONITORING", "await_timeout")

        if self.state == "SUSPENDED":
            suspended = [event for event in self.data["events"] if event["status"] == "suspended"]
            if suspended:
                oldest = min(event["age_turns"] for event in suspended)
                if oldest >= self.config["state"]["suspend_max_turns"]:
                    for event in suspended:
                        if event["age_turns"] >= self.config["state"]["suspend_max_turns"]:
                            event["status"] = "expired"
                            event["outcome"] = "expired"
                    self._set_state("MONITORING", "suspend_expired")
                    events.append(_m(self.language, "expired"))

        # A cycle left mid-flight by a crash or an interrupted run must not trap
        # the machine; resetting to MONITORING keeps later turns monitored.
        if self.state in ("EVALUATING", "RESPONDING", "DETECTED"):
            self._set_state("MONITORING", "stale_cycle_reset")
            self.data["active_event_id"] = None
            events.append("stale cycle reset")

        self.save()
        return {"turn": self.data["turn"], "state": self.state, "events": events}

    def ingest_detection(self, detection: dict[str, Any]) -> dict[str, Any]:
        """Fold one detection into the machine and report the transition."""
        tension_result = detection["tension_result"]
        event_info = detection["conflict_event"]
        mode = self.config["skill"]["mode"]
        previous = self.state

        level = tension_result["level"]
        if mode == "off" or level == "silent":
            self.save()
            return {
                "from": previous,
                "to": self.state,
                "open_events": len(self.open_events()),
                "dropped_event_ids": [],
            }

        event_id = event_info["event_id"]
        existing = self._find(event_id)
        dropped: list[str] = []

        if existing is None:
            existing = {
                "event_id": event_id,
                "turn": self.data["turn"],
                "age_turns": 0,
                "tension": tension_result["tension"],
                "level": level,
                "channel": tension_result["channel"],
                "conflict_type": event_info["conflict_type"],
                "novelty": event_info["novelty"],
                "placebo": bool(detection.get("placebo")),
                "status": "open",
                "outcome": None,
            }
            self.data["events"].append(existing)
        else:
            existing["tension"] = tension_result["tension"]
            existing["level"] = level
            existing["novelty"] = max(existing.get("novelty", 0.0), event_info["novelty"])

        # Overflow policy: the lowest-tension event that is not the active one is
        # dropped to the log. Only the count and the ids are reported; the full
        # record stays in the JSONL log, so no data is lost.
        limit = int(self.config["state"]["max_open_events"])
        while len(self.open_events()) > limit:
            candidates = [e for e in self.open_events() if e["event_id"] != self.data["active_event_id"]]
            if not candidates:
                break
            victim = min(candidates, key=lambda e: (e["tension"], e["turn"]))
            victim["status"] = "dropped"
            victim["outcome"] = "overflow"
            self.data["dropped"].append(victim["event_id"])
            dropped.append(victim["event_id"])

        # Resume a suspended event when *this new* detection carries sufficiently
        # novel evidence. The suspended event's own novelty was fixed when it was
        # deferred, so testing that value instead would make the resume condition
        # permanently false - which is exactly the kind of unreachable exit the
        # suspend state must not have.
        if self.state == "SUSPENDED":
            suspended = [e for e in self.data["events"] if e["status"] == "suspended"]
            threshold = float(self.config["state"]["resume_novelty"])
            if suspended and event_info["novelty"] >= threshold:
                candidate = max(suspended, key=lambda e: e["tension"])
                candidate["status"] = "awaiting"
                self.data["active_event_id"] = candidate["event_id"]
                self._dispatch(candidate, mode)
                self.save()
                return {
                    "from": previous,
                    "to": self.state,
                    "open_events": len(self.open_events()),
                    "dropped_event_ids": dropped,
                    "resumed_event_id": candidate["event_id"],
                    "resume_reason": "novel_evidence",
                }

        if self.state in ("MONITORING", "IDLE"):
            self._set_state("DETECTED", "threshold_crossed")
            self.data["active_event_id"] = event_id
            self._dispatch(existing, mode)
        # In any other state the event stays queued as 'open' and is promoted when
        # the in-flight cycle finishes.

        self.save()
        return {
            "from": previous,
            "to": self.state,
            "open_events": len(self.open_events()),
            "dropped_event_ids": dropped,
        }

    def _dispatch(self, event: dict[str, Any], mode: str) -> None:
        """Send the active event to its next station according to mode/interaction."""
        if mode == "placebo":
            event["status"] = "logged"
            event["outcome"] = "placebo"
            self.data["active_event_id"] = None
            self._set_state("MONITORING", "placebo_logged")
            return
        if mode == "detect_only":
            event["status"] = "logged"
            event["outcome"] = "detect_only"
            self.data["active_event_id"] = None
            self._set_state("MONITORING", "detect_only_logged")
            return
        if self.config["skill"]["interaction"] == "ambient":
            event["status"] = "awaiting"
            self._set_state("EVALUATING", "ambient_auto")
            return
        event["status"] = "awaiting"
        self.data["await_deadline_turn"] = self.data["turn"] + int(self.config["state"]["await_timeout_turns"])
        self._set_state("AWAITING_USER", "await_user")

    # ---- commands ---------------------------------------------------------

    def handle_command(self, text: str) -> dict[str, Any]:
        command = normalise_command(text)
        previous = self.state
        key = self.config["skill"]["language"]

        if command is None:
            self.save()
            return {"command": None, "from": previous, "to": self.state, "accepted": False, "message": _m(key, "unknown")}

        if command == "status":
            self.save()
            return {
                "command": command,
                "from": previous,
                "to": self.state,
                "accepted": True,
                "message": _m(key, "status"),
                "status": self.status(),
            }

        if command == "reset":
            run_id = self.data["run_id"]
            self.data = {
                "state_version": STATE_VERSION,
                "run_id": run_id,
                "state": "MONITORING" if self.config["skill"]["enabled"] else "IDLE",
                "turn": 0,
                "await_deadline_turn": None,
                "active_event_id": None,
                "events": [],
                "history": [],
                "dropped": [],
            }
            self.save()
            return {"command": command, "from": previous, "to": self.state, "accepted": True, "message": _m(key, "reset")}

        if command == "off":
            self._set_state("IDLE", "user_disabled")
            self.data["active_event_id"] = None
            self.data["await_deadline_turn"] = None
            self.save()
            return {"command": command, "from": previous, "to": self.state, "accepted": True, "message": _m(key, "off")}

        if command == "on":
            self._set_state("MONITORING", "user_enabled")
            self.save()
            return {"command": command, "from": previous, "to": self.state, "accepted": True, "message": _m(key, "on")}

        active = self.active_event

        if command == "process":
            if active is None:
                active = self._promote_next()
            if active is None:
                self.save()
                return {"command": command, "from": previous, "to": self.state, "accepted": False, "message": _m(key, "no_active")}
            active["status"] = "awaiting"
            self.data["active_event_id"] = active["event_id"]
            self.data["await_deadline_turn"] = None
            self._set_state("EVALUATING", "user_confirmed")
            self.save()
            return {"command": command, "from": previous, "to": self.state, "accepted": True, "message": _m(key, "process"), "event_id": active["event_id"]}

        if command in ("ignore", "later", "resume"):
            if active is None:
                active = self._promote_next()
            if active is None:
                self.save()
                return {"command": command, "from": previous, "to": self.state, "accepted": False, "message": _m(key, "no_active")}

            if command == "ignore":
                active["status"] = "ignored"
                active["outcome"] = "ignored_by_user"
                self.data["active_event_id"] = None
                self.data["await_deadline_turn"] = None
                self._set_state("MONITORING", "user_ignored")
            elif command == "later":
                active["status"] = "suspended"
                active["age_turns"] = 0
                self.data["active_event_id"] = None
                self.data["await_deadline_turn"] = None
                self._set_state("SUSPENDED", "user_deferred")
            else:  # resume
                self.data["active_event_id"] = active["event_id"]
                self._set_state("EVALUATING", "user_resumed")
            self.save()
            return {"command": command, "from": previous, "to": self.state, "accepted": True, "message": _m(key, command), "event_id": active["event_id"]}

        if command == "details":
            self.save()
            return {
                "command": command,
                "from": previous,
                "to": self.state,
                "accepted": True,
                "message": _m(key, "details"),
                "event_id": active["event_id"] if active else None,
            }

        self.save()  # pragma: no cover - every command above returns
        return {"command": command, "from": previous, "to": self.state, "accepted": False, "message": _m(key, "unknown")}

    def _promote_next(self) -> dict[str, Any] | None:
        pending = [event for event in self.open_events() if event["status"] in ("open", "suspended")]
        if not pending:
            return None
        chosen = max(pending, key=lambda event: (event["tension"], -event["turn"]))
        chosen["status"] = "awaiting"
        self.data["active_event_id"] = chosen["event_id"]
        return chosen

    # ---- evaluation / response -------------------------------------------

    def begin_evaluation(self) -> dict[str, Any]:
        if self.state != "EVALUATING":
            raise StateError(f"evaluate requires state EVALUATING, got {self.state}")
        active = self.active_event
        if active is None:
            raise StateError("evaluate requires an active event")
        active["status"] = "evaluating"
        self.save()
        return {"event_id": active["event_id"], "state": self.state}

    def complete_response(self, *, stance_changed: bool, strategy: str) -> dict[str, Any]:
        if self.state not in ("EVALUATING", "RESPONDING"):
            raise StateError(f"respond requires state EVALUATING or RESPONDING, got {self.state}")
        self._set_state("RESPONDING", "response_produced")
        active = self.active_event
        outcome = "resolved" if stance_changed else "unresolved"
        if active is not None:
            active["status"] = outcome
            active["outcome"] = outcome
            active["strategy"] = strategy
        self.data["active_event_id"] = None
        self.data["await_deadline_turn"] = None
        self._set_state("MONITORING", "cycle_complete")
        self.save()
        return {"event_id": active["event_id"] if active else None, "outcome": outcome, "state": self.state}

    # ---- introspection ----------------------------------------------------

    def status(self) -> dict[str, Any]:
        self._age()
        return {
            "state_version": STATE_VERSION,
            "run_id": self.data["run_id"],
            "state": self.state,
            "turn": self.data["turn"],
            "active_event_id": self.data["active_event_id"],
            "await_deadline_turn": self.data["await_deadline_turn"],
            "open_events": len(self.open_events()),
            "dropped_event_ids": list(self.data["dropped"]),
            "events": list(self.data["events"]),
            "history": list(self.data["history"]),
        }
