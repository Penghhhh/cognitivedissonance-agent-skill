"""Tests for the state machine: transitions, the anti-deadlock timeout, and the queue."""

from __future__ import annotations

import unittest
from pathlib import Path

import context

from cds_index import build_detection
from cds_state import StateError, StateMachine, normalise_command


def detect(packet, config=None):
    return build_detection(packet, config or context.BASE_CONFIG)


def fresh(config=None, path=None):
    return StateMachine(config or context.BASE_CONFIG, "test_run", path)


class TestCommands(unittest.TestCase):
    def test_synonyms_map_to_commands(self):
        for word in ("处理", "评估", "process", "Evaluate", "yes"):
            self.assertEqual(normalise_command(word), "process")
        for word in ("忽略", "ignore", "dismiss"):
            self.assertEqual(normalise_command(word), "ignore")
        for word in ("稍后", "later", "defer"):
            self.assertEqual(normalise_command(word), "later")
        for word in ("详情", "details"):
            self.assertEqual(normalise_command(word), "details")
        for word in ("关闭CDS", "off", "disable"):
            self.assertEqual(normalise_command(word), "off")
        for word in ("状态", "status"):
            self.assertEqual(normalise_command(word), "status")

    def test_punctuation_and_case_are_tolerated(self):
        self.assertEqual(normalise_command("  处理。 "), "process")
        self.assertEqual(normalise_command("IGNORE"), "ignore")

    def test_unrecognised_input_is_not_a_command(self):
        self.assertIsNone(normalise_command("what do you think?"))
        self.assertIsNone(normalise_command(""))


class TestTransitions(unittest.TestCase):
    def test_starts_monitoring_when_enabled(self):
        self.assertEqual(fresh().state, "MONITORING")

    def test_starts_idle_when_disabled(self):
        config = context.config_with(skill={"enabled": False})
        self.assertEqual(fresh(config).state, "IDLE")

    def test_silent_detection_changes_nothing(self):
        machine = fresh()
        machine.advance_turn()
        packet = context.base_packet(relation={"type": "none", "opposition": 0.0, "specificity": 0.0})
        packet.pop("stance")
        packet["evidence"] = []
        machine.ingest_detection(detect(packet))
        self.assertEqual(machine.state, "MONITORING")
        self.assertEqual(machine.open_events(), [])

    def test_ambient_alert_goes_straight_to_evaluating(self):
        machine = fresh()
        machine.advance_turn()
        transition = machine.ingest_detection(detect(context.base_packet()))
        self.assertEqual(transition["from"], "MONITORING")
        self.assertEqual(transition["to"], "EVALUATING")
        self.assertEqual(len(machine.open_events()), 1)

    def test_interactive_alert_waits_for_the_user(self):
        config = context.config_with(skill={"interaction": "interactive"})
        machine = fresh(config)
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        self.assertEqual(machine.state, "AWAITING_USER")
        self.assertIsNotNone(machine.data["await_deadline_turn"])

    def test_detect_only_logs_without_evaluating(self):
        config = context.config_with(skill={"mode": "detect_only"})
        machine = fresh(config)
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        self.assertEqual(machine.state, "MONITORING")
        self.assertEqual(machine.data["events"][0]["outcome"], "detect_only")

    def test_placebo_logs_without_shaping(self):
        config = context.config_with(skill={"mode": "placebo"})
        machine = fresh(config)
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        self.assertEqual(machine.state, "MONITORING")
        self.assertEqual(machine.data["events"][0]["outcome"], "placebo")

    def test_duplicate_detection_is_deduplicated_by_event_id(self):
        machine = fresh()
        machine.advance_turn()
        detection = detect(context.base_packet())
        machine.ingest_detection(detection)
        machine.ingest_detection(detection)
        self.assertEqual(len(machine.data["events"]), 1)


class TestInteractiveDecisions(unittest.TestCase):
    def setUp(self):
        self.config = context.config_with(skill={"interaction": "interactive"})
        self.machine = fresh(self.config)
        self.machine.advance_turn()
        self.machine.ingest_detection(detect(context.base_packet(), self.config))
        self.assertEqual(self.machine.state, "AWAITING_USER")

    def test_process_enters_evaluation(self):
        result = self.machine.handle_command("处理")
        self.assertTrue(result["accepted"])
        self.assertEqual(self.machine.state, "EVALUATING")

    def test_ignore_closes_the_event(self):
        self.machine.handle_command("忽略")
        self.assertEqual(self.machine.state, "MONITORING")
        self.assertEqual(self.machine.data["events"][0]["outcome"], "ignored_by_user")

    def test_later_suspends(self):
        self.machine.handle_command("稍后")
        self.assertEqual(self.machine.state, "SUSPENDED")
        self.assertEqual(self.machine.data["events"][0]["status"], "suspended")

    def test_details_does_not_leave_the_state(self):
        result = self.machine.handle_command("详情")
        self.assertTrue(result["accepted"])
        self.assertEqual(self.machine.state, "AWAITING_USER")

    def test_unrecognised_word_does_not_corrupt_state(self):
        result = self.machine.handle_command("嗯，我再想想")
        self.assertFalse(result["accepted"])
        self.assertEqual(self.machine.state, "AWAITING_USER")

    def test_off_and_on(self):
        self.machine.handle_command("关闭 CDS")
        self.assertEqual(self.machine.state, "IDLE")
        self.machine.handle_command("开启 CDS")
        self.assertEqual(self.machine.state, "MONITORING")

    def test_process_without_an_event_is_a_no_op(self):
        machine = fresh(context.BASE_CONFIG)
        result = machine.handle_command("处理")
        self.assertFalse(result["accepted"])
        self.assertEqual(machine.state, "MONITORING")


class TestNoDeadlock(unittest.TestCase):
    """A machine that can park forever would silently stop monitoring, which is
    worse than a wrong answer because nothing in the transcript would show it."""

    def test_await_times_out_and_records_the_non_decision(self):
        config = context.config_with(skill={"interaction": "interactive"})
        machine = fresh(config)
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        self.assertEqual(machine.state, "AWAITING_USER")

        # await_timeout_turns is 1: the user gets the next turn to answer.
        machine.advance_turn()
        self.assertEqual(machine.state, "AWAITING_USER")

        report = machine.advance_turn()
        self.assertEqual(machine.state, "MONITORING")
        self.assertIsNone(machine.data["active_event_id"])
        self.assertEqual(machine.data["events"][0]["outcome"], "no_decision")
        self.assertTrue(report["events"])

    def test_monitoring_resumes_after_a_timeout(self):
        config = context.config_with(skill={"interaction": "interactive"})
        machine = fresh(config)
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        machine.advance_turn()
        machine.advance_turn()
        self.assertEqual(machine.state, "MONITORING")
        # A later conflict must still be able to fire.
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        self.assertEqual(machine.state, "AWAITING_USER")

    def test_suspend_expires(self):
        config = context.config_with(skill={"interaction": "interactive"})
        machine = fresh(config)
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        machine.handle_command("稍后")
        self.assertEqual(machine.state, "SUSPENDED")

        for _ in range(config["state"]["suspend_max_turns"] + 1):
            machine.advance_turn()
        self.assertEqual(machine.state, "MONITORING")
        self.assertEqual(machine.data["events"][0]["outcome"], "expired")

    def test_novel_evidence_resumes_a_suspended_event(self):
        config = context.config_with(skill={"interaction": "interactive"})
        machine = fresh(config)
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        machine.handle_command("稍后")
        self.assertEqual(machine.state, "SUSPENDED")

        novel = context.base_packet()
        novel["turn_id"] = 9
        novel["evidence"][0]["id"] = "ev_new"
        novel["evidence"][0]["novelty"] = 0.95
        transition = machine.ingest_detection(detect(novel, config))
        self.assertEqual(transition.get("resume_reason"), "novel_evidence")
        # Interactive mode still respects the user's gate: the deferred event is
        # re-offered rather than evaluated behind their back.
        self.assertEqual(machine.state, "AWAITING_USER")
        self.assertEqual(machine.active_event["event_id"], transition["resumed_event_id"])

    def test_novel_evidence_resumes_straight_into_evaluation_when_ambient(self):
        config = context.config_with(skill={"interaction": "interactive"})
        machine = fresh(config)
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet(), config))
        machine.handle_command("稍后")
        machine.config = context.config_with(skill={"interaction": "ambient"})

        novel = context.base_packet()
        novel["turn_id"] = 9
        novel["evidence"][0]["id"] = "ev_new"
        novel["evidence"][0]["novelty"] = 0.95
        transition = machine.ingest_detection(detect(novel, machine.config))
        self.assertEqual(transition.get("resume_reason"), "novel_evidence")
        self.assertEqual(machine.state, "EVALUATING")

    def test_stale_cycle_is_reset_not_trapped(self):
        machine = fresh()
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet()))
        self.assertEqual(machine.state, "EVALUATING")
        machine.advance_turn()
        self.assertEqual(machine.state, "MONITORING")


class TestQueue(unittest.TestCase):
    def test_events_are_queued_while_a_cycle_is_in_flight(self):
        machine = fresh()
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet()))
        self.assertEqual(machine.state, "EVALUATING")

        second = context.base_packet(relation={"type": "evidence_vs_stance", "opposition": 0.95, "specificity": 0.9})
        second["evidence"][0]["id"] = "ev_second"
        machine.ingest_detection(detect(second))
        # The in-flight cycle is not interrupted, but the new event is not lost.
        self.assertEqual(machine.state, "EVALUATING")
        self.assertEqual(len(machine.open_events()), 2)

    def test_overflow_drops_the_lowest_tension_non_active_event(self):
        config = context.config_with(state={"max_open_events": 2})
        machine = fresh(config)
        machine.advance_turn()

        packets = []
        for index, opposition in enumerate((0.90, 0.70, 0.60, 0.55)):
            packet = context.base_packet(relation={"type": "evidence_vs_stance", "opposition": opposition, "specificity": 0.6})
            packet["evidence"][0]["id"] = f"ev_{index}"
            packets.append(packet)

        for packet in packets:
            machine.ingest_detection(detect(packet, config))

        self.assertLessEqual(len(machine.open_events()), 2)
        self.assertTrue(machine.data["dropped"])
        dropped = {event["event_id"]: event for event in machine.data["events"]}
        for event_id in machine.data["dropped"]:
            self.assertEqual(dropped[event_id]["outcome"], "overflow")

    def test_promotion_picks_the_highest_tension_pending_event(self):
        machine = fresh()
        machine.advance_turn()
        low = context.base_packet(relation={"type": "evidence_vs_stance", "opposition": 0.60, "specificity": 0.5})
        low["evidence"][0]["id"] = "ev_low"
        machine.ingest_detection(detect(low))

        high = context.base_packet(relation={"type": "evidence_vs_stance", "opposition": 0.99, "specificity": 0.95})
        high["evidence"][0]["id"] = "ev_high"
        high["turn_id"] = 2
        machine.ingest_detection(detect(high))

        promoted = machine._promote_next()
        self.assertEqual(promoted["tension"], max(event["tension"] for event in machine.data["events"] if event["status"] == "awaiting"))


class TestOutcomes(unittest.TestCase):
    def test_complete_response_marks_resolved_when_the_plan_moves_the_stance(self):
        machine = fresh()
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet()))
        machine.begin_evaluation()
        completion = machine.complete_response(planned_change=True, strategy="qualify")
        self.assertEqual(completion["outcome"], "resolved")
        self.assertEqual(completion["outcome_source"], "planned")
        self.assertEqual(machine.state, "MONITORING")
        self.assertIsNone(machine.data["active_event_id"])

    def test_reduction_leaves_the_event_unresolved(self):
        machine = fresh()
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet()))
        machine.begin_evaluation()
        completion = machine.complete_response(planned_change=False, strategy="trivialize")
        self.assertEqual(completion["outcome"], "unresolved")

    def test_an_observed_outcome_overrides_the_plan_and_says_so(self):
        """A supplied observation must be distinguishable from a plan echo.

        Without this, a log analysis cannot tell "the model complied" from
        "nobody looked at the reply", and the loop's terminal variable silently
        reverts to being a restatement of the routed strategy.
        """
        machine = fresh()
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet()))
        machine.begin_evaluation()
        completion = machine.complete_response(
            planned_change=True, strategy="qualify", observed_outcome="unresolved"
        )
        self.assertEqual(completion["outcome"], "unresolved")
        self.assertEqual(completion["outcome_source"], "observed")
        self.assertEqual(completion["planned_outcome"], "resolved")
        event = machine.data["events"][-1]
        self.assertEqual(event["outcome_source"], "observed")
        self.assertEqual(event["planned_outcome"], "resolved")

    def test_planned_outcome_is_recorded_even_without_an_observation(self):
        machine = fresh()
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet()))
        machine.begin_evaluation()
        machine.complete_response(planned_change=False, strategy="trivialize")
        event = machine.data["events"][-1]
        self.assertEqual(event["outcome_source"], "planned")
        self.assertEqual(event["planned_outcome"], "unresolved")

    def test_begin_evaluation_requires_the_right_state(self):
        machine = fresh()
        with self.assertRaises(StateError):
            machine.begin_evaluation()


class TestPersistence(unittest.TestCase):
    def test_state_round_trips(self):
        with context.scratch_dir() as tmp:
            path = Path(tmp) / "state.json"
            machine = fresh(path=path)
            machine.advance_turn()
            machine.ingest_detection(detect(context.base_packet()))
            machine.save()

            reloaded = StateMachine.load(context.BASE_CONFIG, "test_run", path)
            self.assertEqual(reloaded.state, machine.state)
            self.assertEqual(reloaded.data["turn"], machine.data["turn"])
            self.assertEqual(len(reloaded.data["events"]), 1)

    def test_a_different_run_id_does_not_inherit_state(self):
        with context.scratch_dir() as tmp:
            path = Path(tmp) / "state.json"
            machine = fresh(path=path)
            machine.advance_turn()
            machine.ingest_detection(detect(context.base_packet()))
            machine.save()

            other = StateMachine.load(context.BASE_CONFIG, "different_run", path)
            self.assertEqual(other.data["events"], [])

    def test_status_is_json_serialisable(self):
        import json

        machine = fresh()
        machine.advance_turn()
        machine.ingest_detection(detect(context.base_packet()))
        json.dumps(machine.status())


if __name__ == "__main__":
    unittest.main()
