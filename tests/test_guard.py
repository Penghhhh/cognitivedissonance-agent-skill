"""Tests for the stealth guard (v0.4.0).

Two properties carry the whole design, and both are tested here rather than
asserted in prose:

1. **Silence is real.** When the guard does not surface, the turn must be
   indistinguishable from a turn with no skill installed: no card, no question, one
   line of engine output. A guard that leaked a "nothing found" card would have
   kept the cost it was introduced to remove.
2. **The interruption bar is not the recording bar.** Screening is a separate,
   stricter decision, and it is a pure function of (packet, config, history) - so
   the same packet always produces the same decision, and the reason for every
   held-back event is in the log.

The session-level inhibitors (cooldown, dismissal, budget) are tested through the
state machine as well as through the engine, because a decision that only works
stateless is not the decision the product makes.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

import context

import cds
from cds_config import ConfigError, check_semantics, load_config, load_schema
from cds_guard import (
    R_BELOW_ALERT,
    R_BELOW_SURFACE,
    R_BUDGET,
    R_COOLDOWN,
    R_DISMISSED,
    R_GATED,
    R_INERT,
    R_NO_CONFLICT,
    R_WEAK_OPPOSITION,
    guard_policy,
    run_guard,
    conflict_key,
    escalation_hint,
)
from cds_state import StateMachine
from jsonschema_lite import validate

EXAMPLE = context.REPO_ROOT / "examples" / "packet_evidence_vs_stance.json"
NO_CONFLICT = context.REPO_ROOT / "examples" / "packet_no_conflict.json"


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Invoke the CLI in-process, capturing both streams."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cds.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def fresh_history(**overrides) -> dict:
    history = {"current_turn": 1, "surfaces_count": 0, "last_surface_turn": None, "dismissed": []}
    history.update(overrides)
    return history


class TestScreeningDecision(unittest.TestCase):
    """Which packets reach the user, and which are recorded in silence."""

    def test_a_clear_conflict_surfaces(self):
        result = run_guard(context.base_packet(), context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["decision"], "surface")
        self.assertTrue(result["asks_user"])
        self.assertEqual(result["reasons"], ["policy_ask_user"])
        self.assertEqual(result["next_action"], "await_user_decision")

    def test_no_conflict_is_silent(self):
        packet = context.base_packet(relation={"type": "none", "opposition": 0.0, "specificity": 0.0})
        packet.pop("evidence")
        packet["stance"] = None
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_NO_CONFLICT])

    def test_below_the_alert_threshold_is_silent(self):
        packet = context.base_packet(
            relation={"type": "evidence_vs_stance", "opposition": 0.30, "specificity": 0.20}
        )
        packet["stance"]["commitment"] = 0.20
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["reasons"], [R_BELOW_ALERT])

    def test_between_the_alert_bar_and_the_surface_bar_is_silent(self):
        """The regression that matters: a real but unremarkable conflict.

        The packet must clear `thresholds.alert` (it is a genuine conflict, and the
        detection card must still be reachable for it) while staying under
        `guard.surface_threshold`. If the two bars were ever collapsed into one, this
        test fails and the skill has become a nagger.
        """
        packet = context.base_packet(
            relation={"type": "evidence_vs_stance", "opposition": 0.60, "specificity": 0.55}
        )
        packet["stance"]["commitment"] = 0.50
        packet["evidence"][0]["novelty"] = 0.30
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertGreaterEqual(result["tension"], context.BASE_CONFIG["thresholds"]["alert"])
        self.assertLess(result["tension"], context.BASE_CONFIG["guard"]["surface_threshold"])
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_BELOW_SURFACE])

    def test_weak_opposition_is_silent_even_when_the_index_is_high(self):
        """Commitment and free choice cannot make a barely-conflicting pair obvious."""
        packet = context.base_packet(
            relation={"type": "evidence_vs_stance", "opposition": 0.30, "specificity": 0.90}
        )
        packet["stance"]["commitment"] = 1.0
        packet["stance"]["volition"] = 1.0
        packet["stance"]["self_relevance"] = 1.0
        packet["evidence"][0]["novelty"] = 1.0
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertGreaterEqual(result["tension"], context.BASE_CONFIG["guard"]["surface_threshold"])
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_WEAK_OPPOSITION])

    def test_a_gated_event_never_interrupts_on_the_dissonance_channel(self):
        packet = context.base_packet()
        packet["stance"]["volition"] = 0.20
        packet["stance"]["self_relevance"] = 0.50
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertTrue(result["gated"])
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_GATED])

    def test_an_inert_arm_is_silent(self):
        config = context.config_with(skill={"mode": "off"})
        result = run_guard(context.base_packet(), config, history=fresh_history())
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_INERT])
        self.assertEqual(guard_policy(config), "ask")

    def test_disabling_the_guard_is_silent(self):
        config = context.config_with(guard={"enabled": False})
        result = run_guard(context.base_packet(), config, history=fresh_history())
        self.assertEqual(result["reasons"], [R_INERT])


class TestSessionInhibitors(unittest.TestCase):
    """The guard must not ask twice about the same thing."""

    def test_cooldown_silences_the_next_turn(self):
        result = run_guard(
            context.base_packet(), context.BASE_CONFIG, history=fresh_history(current_turn=5, last_surface_turn=4)
        )
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_COOLDOWN])

    def test_cooldown_expires(self):
        result = run_guard(
            context.base_packet(), context.BASE_CONFIG, history=fresh_history(current_turn=9, last_surface_turn=4)
        )
        self.assertEqual(result["decision"], "surface")

    def test_a_dismissed_conflict_is_not_raised_again(self):
        key = conflict_key(context.base_packet())
        result = run_guard(
            context.base_packet(),
            context.BASE_CONFIG,
            history=fresh_history(dismissed=[{"conflict_key": key, "turn": 2, "decision": "ignore"}]),
        )
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_DISMISSED])

    def test_a_dismissed_conflict_returns_when_the_evidence_is_new(self):
        """A dismissal is about a restated objection, not about the topic forever."""
        packet = context.base_packet()
        packet["evidence"][0]["novelty"] = 0.95
        key = conflict_key(packet)
        result = run_guard(
            packet,
            context.BASE_CONFIG,
            history=fresh_history(dismissed=[{"conflict_key": key, "turn": 2, "decision": "ignore"}]),
        )
        self.assertEqual(result["decision"], "surface")

    def test_the_surface_budget_is_enforced(self):
        budget = context.BASE_CONFIG["guard"]["max_surfaces_per_run"]
        result = run_guard(
            context.base_packet(), context.BASE_CONFIG, history=fresh_history(surfaces_count=budget)
        )
        self.assertEqual(result["decision"], "silent")
        self.assertEqual(result["reasons"], [R_BUDGET])

    def test_the_budget_can_be_switched_off(self):
        config = context.config_with(guard={"max_surfaces_per_run": 0})
        result = run_guard(context.base_packet(), config, history=fresh_history(surfaces_count=99))
        self.assertEqual(result["decision"], "surface")


class TestPoliciesAndArms(unittest.TestCase):
    """The guard asks, auto-escalates or stays in the log, and the arm wins."""

    def test_auto_policy_escalates_without_asking(self):
        config = context.config_with(guard={"policy": "auto"})
        result = run_guard(context.base_packet(), config, history=fresh_history())
        self.assertEqual(result["next_action"], "auto_evaluate")
        self.assertFalse(result["asks_user"])

    def test_log_only_policy_surfaces_nothing_to_the_user(self):
        config = context.config_with(guard={"policy": "log_only"})
        result = run_guard(context.base_packet(), config, history=fresh_history())
        self.assertEqual(result["decision"], "surface")
        self.assertFalse(result["asks_user"])
        self.assertEqual(result["next_action"], "log_only")

    def test_detect_only_arm_never_reaches_the_user(self):
        config = context.config_with(skill={"mode": "detect_only"})
        result = run_guard(context.base_packet(), config, history=fresh_history())
        self.assertFalse(result["asks_user"])
        self.assertEqual(result["next_action"], "log_only")

    def test_placebo_arm_keeps_the_full_cadence(self):
        """The control must have the same shape, so it asks exactly as `full` does."""
        config = context.config_with(skill={"mode": "placebo"})
        result = run_guard(context.base_packet(), config, history=fresh_history())
        self.assertEqual(result["decision"], "surface")
        self.assertTrue(result["asks_user"])
        self.assertTrue(result["placebo"])


class TestGuardRecord(unittest.TestCase):
    """The record is the audit surface, so it is schema-checked and reproducible."""

    def test_the_record_satisfies_its_published_schema(self):
        result = run_guard(context.base_packet(), context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(validate(load_schema("guard"), result), [])

    def test_the_embedded_detection_satisfies_the_detection_schema(self):
        result = run_guard(context.base_packet(), context.BASE_CONFIG, history=fresh_history())
        detection = dict(result["detection"])
        detection["state"] = {"from": "MONITORING", "to": "MONITORING", "open_events": 0}
        self.assertEqual(validate(load_schema("detection"), detection), [])

    def test_identical_inputs_give_an_identical_record(self):
        first = run_guard(context.base_packet(), context.BASE_CONFIG, history=fresh_history())
        second = run_guard(context.base_packet(), context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(first, second)

    def test_the_conflict_key_is_stable_and_claim_derived(self):
        first = conflict_key(context.base_packet())
        second = conflict_key(context.base_packet())
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("cds_key_"))

        packet = context.base_packet()
        packet["evidence"][0]["claim"] = "a different claim entirely"
        self.assertNotEqual(first, conflict_key(packet))

    def test_the_conflict_key_ignores_surrounding_whitespace(self):
        packet = context.base_packet()
        spaced = context.base_packet()
        spaced["evidence"][0]["claim"] = f"  {packet['evidence'][0]['claim']}  "
        self.assertEqual(conflict_key(packet), conflict_key(spaced))

    def test_escalation_hint_distinguishes_the_paths(self):
        surface = run_guard(context.base_packet(), context.BASE_CONFIG, history=fresh_history())
        # The hint is a *stop* instruction, not a display instruction. v0.4.0 said
        # "show the card and wait for the user decision", and what a host model did
        # with that was finish its answer and append the card to it.
        hint = escalation_hint(surface)
        self.assertIn("STOP", hint)
        self.assertIn("wait", hint)
        self.assertIn("Do not write the answer first", hint)

        silent_packet = context.base_packet(relation={"type": "none", "opposition": 0.0, "specificity": 0.0})
        silent_packet.pop("evidence")
        silent_packet["stance"] = None
        silent = run_guard(silent_packet, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(escalation_hint(silent), "CDS_GUARD silent")


class TestClaimRoles(unittest.TestCase):
    """The two sides of a conflict are named from the conflict type, not guessed."""

    def test_evidence_vs_stance_pairs_stance_with_evidence(self):
        result = run_guard(context.base_packet(), context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["claims"]["a"]["role"], "stance")
        self.assertEqual(result["claims"]["b"]["role"], "evidence")

    def test_user_hint_is_named_as_pressure_not_evidence(self):
        packet = context.base_packet(relation={"type": "user_hint_vs_stance", "opposition": 0.80, "specificity": 0.70})
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["claims"]["a"]["role"], "stance")
        self.assertEqual(result["claims"]["b"]["role"], "user_hint")

    def test_memory_vs_current_names_both_sides(self):
        packet = context.base_packet(relation={"type": "memory_vs_current", "opposition": 0.80, "specificity": 0.70})
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["claims"]["a"]["role"], "memory")
        self.assertEqual(result["claims"]["b"]["role"], "current")

    def test_evidence_vs_evidence_names_two_sources(self):
        packet = context.base_packet(
            relation={"type": "evidence_vs_evidence", "opposition": 0.80, "specificity": 0.70},
            evidence=[
                {"id": "ev_001", "claim": "延迟下降", "carries_conflict": True, "novelty": 0.6},
                {"id": "ev_002", "claim": "延迟上升", "carries_conflict": True, "novelty": 0.6},
            ],
        )
        result = run_guard(packet, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["claims"]["a"]["role"], "evidence")
        self.assertEqual(result["claims"]["b"]["role"], "evidence")
        self.assertEqual(result["claims"]["a"]["text"], "延迟下降")


class TestSparsePackets(unittest.TestCase):
    """A screening packet is a full signal packet with only the index terms filled."""

    SPARSE = {
        "run_id": "sparse_run",
        "turn_id": 1,
        "relation": {"type": "evidence_vs_stance", "opposition": 0.85, "specificity": 0.80},
        "stance": {
            "id": "stance_001",
            "claim": "该方案在当前规模下是可行的",
            "source": "prior_conversation",
            "anchor": "第 3 轮我说：该方案在当前规模下是可行的",
            "commitment": 0.70,
            "public_commitment": 0.60,
            "volition": 0.85,
            "self_relevance": 0.90,
        },
        "evidence": [{"id": "ev_001", "claim": "压测显示该方案在目标规模下失败", "novelty": 0.80}],
    }

    def test_a_sparse_packet_is_a_valid_signal_packet(self):
        self.assertEqual(validate(load_schema("signals"), self.SPARSE), [])

    def test_a_sparse_packet_screens(self):
        result = run_guard(self.SPARSE, context.BASE_CONFIG, history=fresh_history())
        self.assertEqual(result["decision"], "surface")
        self.assertEqual(result["claims"]["b"]["text"], "压测显示该方案在目标规模下失败")

    def test_absent_evaluator_dimensions_are_not_invented(self):
        """The screening stage must not fabricate evidence-quality ratings.

        It never reads them, so a missing dimension must stay missing: a fabricated
        zero would silently drag the evaluator's score down later, and a fabricated
        middle value would be worse.
        """
        result = run_guard(self.SPARSE, context.BASE_CONFIG, history=fresh_history())
        for dimension in ("relevance", "credibility", "recency", "independence", "consistency"):
            with self.subTest(dimension=dimension):
                self.assertNotIn(dimension, self.SPARSE["evidence"][0])


class TestConfigSemantics(unittest.TestCase):
    """A guard looser than the recording bar is refused, not documented away."""

    def test_surface_threshold_below_the_alert_bar_is_refused(self):
        config = json.loads(json.dumps(context.BASE_CONFIG))
        config["guard"]["surface_threshold"] = 0.40
        with self.assertRaises(ConfigError) as caught:
            check_semantics(config)
        self.assertIn("surface_threshold", str(caught.exception))

    def test_surface_threshold_at_the_alert_bar_is_allowed(self):
        config = json.loads(json.dumps(context.BASE_CONFIG))
        config["guard"]["surface_threshold"] = config["thresholds"]["alert"]
        check_semantics(config)

    def test_the_shipped_config_is_coherent(self):
        check_semantics(load_config())


class TestGuardCli(unittest.TestCase):
    """The command-line surface, including the one-line silent path."""

    def test_silent_turn_prints_one_line_and_no_card(self):
        with context.scratch_dir() as tmp:
            code, out, _ = run_cli(
                "guard", "--signals", str(NO_CONFLICT), "--state", str(Path(tmp) / "s.json"),
                "--no-log",
            )
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), "CDS_GUARD silent")

    def test_clear_conflict_prints_the_card_and_the_hint(self):
        with context.scratch_dir() as tmp:
            code, out, _ = run_cli(
                "guard", "--signals", str(EXAMPLE), "--state", str(Path(tmp) / "s.json"), "--no-log"
            )
            self.assertEqual(code, 0)
            self.assertIn("CDS_GUARD surface", out)
            self.assertIn("观点1", out)
            self.assertIn("是否进入评估？", out)

    def test_card_only_prints_only_the_card(self):
        with context.scratch_dir() as tmp:
            code, out, _ = run_cli(
                "guard", "--signals", str(EXAMPLE), "--state", str(Path(tmp) / "s.json"),
                "--no-log", "--card-only",
            )
            self.assertEqual(code, 0)
            self.assertNotIn("CDS_GUARD", out)
            self.assertIn("观点1", out)

    def test_json_prints_the_record(self):
        with context.scratch_dir() as tmp:
            code, out, _ = run_cli(
                "guard", "--signals", str(EXAMPLE), "--state", str(Path(tmp) / "s.json"),
                "--no-log", "--json",
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["decision"], "surface")
            self.assertEqual(validate(load_schema("guard"), payload), [])

    def test_the_guard_stage_is_logged(self):
        with context.scratch_dir() as tmp:
            log = Path(tmp) / "logs" / "cds.jsonl"
            code, _, _ = run_cli(
                "guard", "--signals", str(EXAMPLE), "--state", str(Path(tmp) / "s.json"), "--log", str(log)
            )
            self.assertEqual(code, 0)
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([record["stage"] for record in records], ["guard"])

    def test_a_silent_turn_is_logged_too(self):
        """The denominator has to exist, or the false-negative rate is unknowable."""
        with context.scratch_dir() as tmp:
            log = Path(tmp) / "logs" / "cds.jsonl"
            code, _, _ = run_cli(
                "guard", "--signals", str(NO_CONFLICT), "--state", str(Path(tmp) / "s.json"), "--log", str(log)
            )
            self.assertEqual(code, 0)
            record = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["stage"], "guard")
            self.assertEqual(record["payload"]["decision"], "silent")

    def test_the_state_file_records_the_screening(self):
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            run_cli("guard", "--signals", str(EXAMPLE), "--state", str(state), "--no-log")
            code, out, _ = run_cli("status", "--state", str(state), "--json")
            self.assertEqual(code, 0)
            guard = json.loads(out)["guard"]
            self.assertEqual(guard["surfaces"], 1)
            self.assertTrue(guard["awaiting_confirmation"])

    def test_detect_does_not_advance_the_turn_a_second_time(self):
        """The screening and the event it escalated to belong to one turn."""
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            run_cli("guard", "--signals", str(EXAMPLE), "--state", str(state), "--no-log")
            after_guard = StateMachine.load(context.BASE_CONFIG, None, state).data["turn"]
            run_cli("detect", "--signals", str(EXAMPLE), "--state", str(state), "--no-log")
            after_detect = StateMachine.load(context.BASE_CONFIG, None, state).data["turn"]
            self.assertEqual(after_guard, after_detect)


class TestStealthLoop(unittest.TestCase):
    """The whole point: consent once, and the full loop runs exactly once."""

    def test_consent_carries_into_the_evaluation(self):
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            detection_path = Path(tmp) / "detection.json"
            evaluation_path = Path(tmp) / "evaluation.json"

            code, out, _ = run_cli(
                "guard", "--signals", str(EXAMPLE), "--state", str(state), "--no-log", "--card-only"
            )
            self.assertEqual(code, 0)
            self.assertIn("是否进入评估？", out)

            code, out, _ = run_cli("command", "处理", "--state", str(state), "--no-log")
            self.assertEqual(code, 0)
            self.assertIn("进入评估", out)

            code, out, _ = run_cli(
                "detect", "--signals", str(EXAMPLE), "--state", str(state), "--no-log",
                "--brief", "--out", str(detection_path),
            )
            self.assertEqual(code, 0)
            self.assertIn("已确认冲突", out)

            code, _, _ = run_cli(
                "evaluate", "--detection", str(detection_path), "--signals", str(EXAMPLE),
                "--state", str(state), "--no-log", "--out", str(evaluation_path),
            )
            self.assertEqual(code, 0, "consent must leave the machine in EVALUATING")

            machine = StateMachine.load(context.BASE_CONFIG, None, state)
            self.assertTrue(machine.active_event.get("user_consent"))
            self.assertEqual(machine.state, "EVALUATING")

    def test_the_user_is_not_asked_a_second_time_on_the_detection_card(self):
        """Consent recorded at screening must be honoured, not re-solicited."""
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            run_cli("guard", "--signals", str(EXAMPLE), "--state", str(state), "--no-log")
            run_cli("command", "处理", "--state", str(state), "--no-log")
            run_cli("detect", "--signals", str(EXAMPLE), "--state", str(state), "--no-log")
            machine = StateMachine.load(context.BASE_CONFIG, None, state)
            self.assertEqual(machine.state, "EVALUATING")
            self.assertIsNone(machine.data["await_deadline_turn"])

    def test_ignore_suppresses_the_same_conflict_afterwards(self):
        """A dismissal holds while the objection is a restatement, not new evidence.

        The packet's novelty is held below `guard.resurface_novelty` on purpose:
        `examples/packet_evidence_vs_stance.json` carries novelty 0.80 and would
        legitimately come back, so using it here would test the resurface rule while
        claiming to test the dismissal rule.
        """
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            packet = json.loads(EXAMPLE.read_text(encoding="utf-8"))
            packet["evidence"][0]["novelty"] = 0.30
            restated = Path(tmp) / "restated.json"
            restated.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")

            code, _, _ = run_cli("guard", "--signals", str(restated), "--state", str(state), "--no-log")
            self.assertEqual(code, 0)
            code, _, _ = run_cli("command", "忽略", "--state", str(state), "--no-log")
            self.assertEqual(code, 0)

            code, out, _ = run_cli(
                "guard", "--signals", str(restated), "--state", str(state), "--no-log",
                "--json", "--no-turn-advance",
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["decision"], "silent")
            self.assertIn(R_DISMISSED, json.loads(out)["reasons"])

    def test_novel_evidence_reopens_a_dismissed_conflict(self):
        """The shipped example carries novelty 0.80, above the resurface bar.

        The second screening advances the turn, so the cooldown has expired and the
        dismissal is the only inhibitor left to bypass; otherwise this would pass for
        the wrong reason.
        """
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            run_cli("guard", "--signals", str(EXAMPLE), "--state", str(state), "--no-log")
            run_cli("command", "忽略", "--state", str(state), "--no-log")
            code, out, _ = run_cli(
                "guard", "--signals", str(EXAMPLE), "--state", str(state), "--no-log", "--json"
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["decision"], "surface")
            self.assertTrue(payload["history"]["dismissed_before"])
            self.assertGreaterEqual(payload["novelty"], context.BASE_CONFIG["guard"]["resurface_novelty"])

    def test_later_is_recorded_as_its_own_decision(self):
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            run_cli("guard", "--signals", str(EXAMPLE), "--state", str(state), "--no-log")
            run_cli("command", "稍后", "--state", str(state), "--no-log")
            machine = StateMachine.load(context.BASE_CONFIG, None, state)
            self.assertEqual(machine.data["guard"]["dismissed"][-1]["decision"], "later")

    def test_a_command_with_no_confirmation_still_reports_no_event(self):
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            code, out, _ = run_cli("command", "处理", "--state", str(state), "--no-log")
            self.assertEqual(code, 0)
            self.assertIn("没有待处理", out)


class TestStateUpgrade(unittest.TestCase):
    """A state file written by v0.3.0 must keep working."""

    def test_a_pre_v040_state_file_gains_the_guard_block(self):
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            state.write_text(
                json.dumps(
                    {
                        "state_version": "0.2.0",
                        "run_id": "test_run",
                        "state": "MONITORING",
                        "turn": 7,
                        "await_deadline_turn": None,
                        "active_event_id": None,
                        "events": [],
                        "history": [],
                        "dropped": [],
                    }
                ),
                encoding="utf-8",
            )
            machine = StateMachine.load(context.BASE_CONFIG, None, state)
            history = machine.guard_history()
            self.assertEqual(history["current_turn"], 7)
            self.assertEqual(history["surfaces_count"], 0)
            self.assertEqual(history["dismissed"], [])

    def test_reset_clears_the_guard_memory(self):
        with context.scratch_dir() as tmp:
            state = Path(tmp) / "s.json"
            run_cli("guard", "--signals", str(EXAMPLE), "--state", str(state), "--no-log")
            run_cli("command", "忽略", "--state", str(state), "--no-log")
            run_cli("command", "重置", "--state", str(state), "--no-log")
            machine = StateMachine.load(context.BASE_CONFIG, None, state)
            self.assertEqual(machine.data["guard"]["dismissed"], [])
            self.assertEqual(machine.data["guard"]["surfaces"], [])


if __name__ == "__main__":
    unittest.main()
