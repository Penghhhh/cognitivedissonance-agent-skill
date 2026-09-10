"""End-to-end CLI tests, including the multi-process interactive loop."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

import context

import cds
from cds_config import load_schema
from jsonschema_lite import validate

EXAMPLE = context.REPO_ROOT / "examples" / "packet_evidence_vs_stance.json"


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Invoke the CLI in-process, capturing both streams."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cds.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestBasicCommands(unittest.TestCase):
    def test_config_command(self):
        code, out, _ = run_cli("config", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["index_version"], context.BASE_CONFIG["index"]["index_version"])
        self.assertTrue(payload["config_hash"].startswith("sha256:"))

    def test_selftest_command(self):
        code, out, _ = run_cli("selftest")
        self.assertEqual(code, 0)
        self.assertIn("selftest OK", out)

    def test_status_on_a_fresh_state_file(self):
        with context.scratch_dir() as tmp:
            code, out, _ = run_cli("status", "--state", str(Path(tmp) / "s.json"), "--json")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["state"], "MONITORING")

    def test_validate_accepts_the_shipped_example(self):
        code, out, _ = run_cli("validate", "--signals", str(EXAMPLE))
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_validate_rejects_a_bad_packet(self):
        with context.scratch_dir() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"run_id": "r", "turn_id": 1, "relation": {"type": "nonsense"}}), encoding="utf-8")
            code, _, err = run_cli("validate", "--signals", str(bad))
            self.assertEqual(code, cds.EXIT_INVALID_INPUT)
            self.assertIn("schema validation", err)

    def test_missing_file_is_a_usage_error(self):
        code, _, err = run_cli("validate", "--signals", "does_not_exist.json")
        self.assertEqual(code, cds.EXIT_INVALID_INPUT)
        self.assertIn("file not found", err)

    def test_global_flags_work_before_and_after_the_subcommand(self):
        before = run_cli("--json", "config")
        after = run_cli("config", "--json")
        self.assertEqual(before[0], 0)
        self.assertEqual(after[0], 0)
        self.assertEqual(json.loads(before[1]), json.loads(after[1]))


class TestRunCommand(unittest.TestCase):
    def test_run_produces_a_schema_valid_loop(self):
        code, out, _ = run_cli("run", "--signals", str(EXAMPLE), "--no-log", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)

        errors = validate(load_schema("detection"), payload["detection"])
        self.assertEqual(errors, [], f"detection schema violations: {errors}")
        errors = validate(load_schema("evaluation"), payload["evaluation"])
        self.assertEqual(errors, [], f"evaluation schema violations: {errors}")
        self.assertEqual(payload["state"], "MONITORING")

    def test_run_is_deterministic(self):
        first = json.loads(run_cli("run", "--signals", str(EXAMPLE), "--no-log", "--json")[1])
        second = json.loads(run_cli("run", "--signals", str(EXAMPLE), "--no-log", "--json")[1])
        # The state block reports the turn counter, so compare the arithmetic.
        self.assertEqual(first["detection"]["conflict_event"], second["detection"]["conflict_event"])
        self.assertEqual(first["evaluation"]["evaluation_result"], second["evaluation"]["evaluation_result"])

    def test_card_only_prints_a_card(self):
        code, out, _ = run_cli("run", "--signals", str(EXAMPLE), "--no-log", "--card-only")
        self.assertEqual(code, 0)
        self.assertIn("【CDS｜检测】", out)
        self.assertNotIn("{", out)

    def test_run_refuses_in_interactive_mode(self):
        with context.scratch_dir() as tmp:
            config = json.loads((context.REPO_ROOT / "config" / "cds.config.json").read_text(encoding="utf-8"))
            config["skill"]["interaction"] = "interactive"
            path = Path(tmp) / "cfg.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            code, _, err = run_cli("run", "--signals", str(EXAMPLE), "--config", str(path), "--no-log")
            self.assertEqual(code, cds.EXIT_USAGE)
            self.assertIn("interactive", err)


class TestInteractiveLoop(unittest.TestCase):
    """Four separate CLI invocations must behave as one continuous run."""

    def _config(self, tmp: Path, **skill_overrides) -> Path:
        config = json.loads((context.REPO_ROOT / "config" / "cds.config.json").read_text(encoding="utf-8"))
        config["skill"].update(skill_overrides)
        path = tmp / "cfg.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def test_full_interactive_cycle(self):
        with context.scratch_dir() as tmp:
            state = tmp / "state.json"
            config_path = self._config(tmp, interaction="interactive")

            code, out, _ = run_cli(
                "detect", "--signals", str(EXAMPLE), "--state", str(state),
                "--config", str(config_path), "--no-log", "--json", "--out", str(tmp / "d.json"),
            )
            self.assertEqual(code, 0)
            detection = json.loads(out)
            self.assertEqual(detection["state"]["to"], "AWAITING_USER")

            code, out, _ = run_cli("command", "处理", "--state", str(state), "--config", str(config_path), "--no-log", "--json")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["to"], "EVALUATING")

            code, out, _ = run_cli(
                "evaluate", "--detection", str(tmp / "d.json"), "--signals", str(EXAMPLE),
                "--state", str(state), "--config", str(config_path), "--no-log", "--json",
                "--out", str(tmp / "e.json"),
            )
            self.assertEqual(code, 0)
            evaluation = json.loads(out)
            self.assertEqual(validate(load_schema("evaluation"), evaluation), [])

            code, out, _ = run_cli(
                "respond", "--evaluation", str(tmp / "e.json"),
                "--state", str(state), "--config", str(config_path), "--no-log", "--json",
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["outcome"], "resolved")

            code, out, _ = run_cli("status", "--state", str(state), "--config", str(config_path), "--json")
            self.assertEqual(json.loads(out)["state"], "MONITORING")

    def test_the_user_decision_survives_across_processes(self):
        """The bug this guards: a fresh run id per invocation discards the state file."""
        with context.scratch_dir() as tmp:
            state = tmp / "state.json"
            config_path = self._config(tmp, interaction="interactive")
            run_cli("detect", "--signals", str(EXAMPLE), "--state", str(state),
                    "--config", str(config_path), "--no-log", "--json")
            run_cli("command", "稍后", "--state", str(state), "--config", str(config_path), "--no-log", "--json")
            _, out, _ = run_cli("status", "--state", str(state), "--config", str(config_path), "--json")
            self.assertEqual(json.loads(out)["state"], "SUSPENDED")

    def test_ignore_closes_the_event(self):
        with context.scratch_dir() as tmp:
            state = tmp / "state.json"
            config_path = self._config(tmp, interaction="interactive")
            run_cli("detect", "--signals", str(EXAMPLE), "--state", str(state),
                    "--config", str(config_path), "--no-log", "--json")
            run_cli("command", "忽略", "--state", str(state), "--config", str(config_path), "--no-log", "--json")
            _, out, _ = run_cli("status", "--state", str(state), "--config", str(config_path), "--json")
            status = json.loads(out)
            self.assertEqual(status["state"], "MONITORING")
            self.assertEqual(status["events"][0]["outcome"], "ignored_by_user")


class TestWithheldArms(unittest.TestCase):
    def test_evaluate_refuses_in_detect_only(self):
        with context.scratch_dir() as tmp:
            config = json.loads((context.REPO_ROOT / "config" / "cds.config.json").read_text(encoding="utf-8"))
            config["skill"]["mode"] = "detect_only"
            path = tmp / "cfg.json"
            path.write_text(json.dumps(config), encoding="utf-8")

            code, out, _ = run_cli("run", "--signals", str(EXAMPLE), "--config", str(path), "--no-log", "--json")
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertIsNone(payload["evaluation"])
            self.assertEqual(payload["detection"]["tension_result"]["next_action"], "log_only")

            _, out, _ = run_cli(
                "detect", "--signals", str(EXAMPLE), "--config", str(path), "--no-log", "--json",
                "--out", str(tmp / "d.json"),
            )
            code, _, err = run_cli(
                "evaluate", "--detection", str(tmp / "d.json"), "--signals", str(EXAMPLE),
                "--config", str(path), "--no-log", "--json",
            )
            self.assertEqual(code, cds.EXIT_STATE)
            self.assertIn("must not run", err)


class TestConfigOverrides(unittest.TestCase):
    """`--set` is how study arms are swept, so the invariants must still apply."""

    def _payload(self, *extra: str):
        code, out, err = run_cli("run", "--signals", str(EXAMPLE), "--no-log", "--json", *extra)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_profile_can_be_switched_without_editing_a_file(self):
        payload = self._payload("--set", "skill.profile=dissonance_reduction")
        result = payload["evaluation"]["evaluation_result"]
        self.assertEqual(result["resolved_profile"], "dissonance_reduction")
        self.assertEqual(payload["evaluation"]["response_plan"]["branch"], "dissonance_reduction")

    def test_numeric_values_are_parsed_as_numbers(self):
        payload = self._payload("--set", "thresholds.alert=0.70")
        # evidence_vs_stance has no per-type override, so the global knob is live.
        self.assertEqual(payload["detection"]["tension_result"]["threshold_alert"], 0.70)
        self.assertEqual(payload["detection"]["tension_result"]["threshold_source"], "global")
        # 0.7125 is still above 0.70, so the event still fires
        self.assertEqual(payload["detection"]["tension_result"]["level"], "alert")

    def test_a_per_type_override_beats_the_global_threshold(self):
        payload = self._payload("--set", "thresholds_by_type.evidence_vs_stance=0.70")
        self.assertEqual(payload["detection"]["tension_result"]["threshold_alert"], 0.70)
        self.assertEqual(
            payload["detection"]["tension_result"]["threshold_source"],
            "thresholds_by_type:evidence_vs_stance",
        )

    def test_override_changes_the_config_hash(self):
        base = self._payload()
        patched = self._payload("--set", "thresholds.alert=0.70")
        self.assertNotEqual(base["detection"]["config_hash"], patched["detection"]["config_hash"])

    def test_override_that_breaks_an_invariant_is_refused(self):
        code, _, err = run_cli(
            "run", "--signals", str(EXAMPLE), "--no-log", "--card-only",
            "--set", "index.gates.non_dissonant_cap=0.9",
        )
        self.assertEqual(code, cds.EXIT_USAGE)
        self.assertIn("strictly below every alert threshold", err)

    def test_override_that_breaks_a_weight_sum_is_refused(self):
        code, _, err = run_cli("config", "--set", "index.weights.opposition=0.9")
        self.assertEqual(code, cds.EXIT_USAGE)
        self.assertIn("must sum to 1.0", err)

    def test_unknown_path_is_refused(self):
        code, _, err = run_cli("config", "--set", "nope.nope=1")
        self.assertEqual(code, cds.EXIT_USAGE)
        self.assertIn("does not exist", err)

    def test_malformed_override_is_refused(self):
        code, _, err = run_cli("config", "--set", "not-a-pair")
        self.assertEqual(code, cds.EXIT_USAGE)
        self.assertIn("key=value", err)

    def test_ablation_arms_are_reachable_by_override(self):
        payload = self._payload("--set", "skill.mode=detect_only")
        self.assertIsNone(payload["evaluation"])
        self.assertEqual(payload["detection"]["tension_result"]["next_action"], "log_only")


class TestEncodingTolerance(unittest.TestCase):
    def test_a_config_with_a_byte_order_mark_is_accepted(self):
        with context.scratch_dir() as tmp:
            source = context.REPO_ROOT / "config" / "cds.config.json"
            target = Path(tmp) / "bom.json"
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8-sig")
            self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
            code, out, err = run_cli("config", "--config", str(target), "--json")
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["config_hash"].startswith("sha256:"))

    def test_a_packet_with_a_byte_order_mark_is_accepted(self):
        with context.scratch_dir() as tmp:
            target = Path(tmp) / "packet.json"
            target.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8-sig")
            code, out, err = run_cli("validate", "--signals", str(target))
            self.assertEqual(code, 0, err)
            self.assertIn("OK", out)


class TestExampleDocumentation(unittest.TestCase):
    """examples/README.md publishes a table; make sure the code still matches it."""

    def test_documented_example_table_holds(self):
        import check_examples

        for name, want_level, want_channel, want_strategy in check_examples.EXPECTED:
            with self.subTest(packet=name):
                packet = context.REPO_ROOT / "examples" / name
                self.assertTrue(packet.exists(), f"{name} is documented but missing")
                got = check_examples.observe(packet)
                self.assertEqual(got, (want_level, want_channel, want_strategy))

    def test_observe_decodes_utf8_regardless_of_locale(self):
        """Regression guard: reading the child's UTF-8 stdout with the locale codec
        (GBK on a Chinese Windows runner) raised UnicodeDecodeError before any
        assertion ran, so the checker failed for a reason that looks nothing like
        the real cause."""
        import check_examples

        level, channel, _ = check_examples.observe(context.REPO_ROOT / "examples" / "packet_evidence_vs_stance.json")
        self.assertEqual((level, channel), ("alert", "dissonance"))

    def test_a_packet_that_disagrees_with_the_table_is_reported(self):
        """The checker must actually be able to fail."""
        import check_examples

        original = check_examples.EXPECTED
        check_examples.EXPECTED = [("packet_no_conflict.json", "high", "dissonance", "recalibrate")]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_examples.main(), 1)
        finally:
            check_examples.EXPECTED = original


if __name__ == "__main__":
    unittest.main()
