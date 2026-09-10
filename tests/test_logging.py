"""Tests for the audit log: envelope completeness and content-addressed ids."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import context

from cds_config import load_schema
from cds_index import build_detection
from cds_log import append_record, build_record, read_records
from jsonschema_lite import validate


def make_record(**overrides):
    packet = context.base_packet()
    detection = build_detection(packet, context.BASE_CONFIG)
    kwargs = {
        "config": context.BASE_CONFIG,
        "run_id": "test_run",
        "turn_id": 1,
        "stage": "detect",
        "payload": detection,
        "event_id": detection["conflict_event"]["event_id"],
        "signals": packet,
        "timestamp": "2026-01-01T00:00:00Z",
    }
    kwargs.update(overrides)
    return build_record(**kwargs)


class TestEnvelope(unittest.TestCase):
    def test_envelope_satisfies_the_published_schema(self):
        errors = validate(load_schema("log_record"), make_record())
        self.assertEqual(errors, [], f"log schema violations: {errors}")

    def test_envelope_pins_the_instrument(self):
        record = make_record()
        self.assertEqual(record["index_version"], context.BASE_CONFIG["index"]["index_version"])
        self.assertTrue(record["config_hash"].startswith("sha256:"))
        self.assertTrue(record["signals_hash"].startswith("sha256:"))
        self.assertTrue(record["record_id"].startswith("cds_rec_"))

    def test_model_metadata_is_recorded_when_supplied(self):
        record = make_record(model={"provider": "p", "name": "m", "version": "1", "temperature": 0.0, "seed": 7})
        self.assertEqual(record["model"]["seed"], 7)
        errors = validate(load_schema("log_record"), record)
        self.assertEqual(errors, [])

    def test_absent_model_metadata_is_null_not_missing(self):
        self.assertIsNone(make_record()["model"])


class TestDeterminism(unittest.TestCase):
    def test_identical_inputs_yield_identical_record_ids(self):
        self.assertEqual(make_record()["record_id"], make_record()["record_id"])

    def test_timestamp_does_not_affect_the_record_id(self):
        first = make_record(timestamp="2026-01-01T00:00:00Z")
        second = make_record(timestamp="2030-06-06T12:00:00Z")
        self.assertEqual(first["record_id"], second["record_id"])
        self.assertNotEqual(first["ts"], second["ts"])

    def test_changing_the_config_changes_the_record_id(self):
        other = context.config_with(thresholds={"alert": 0.50})
        self.assertNotEqual(make_record()["record_id"], make_record(config=other)["record_id"])

    def test_changing_the_signals_changes_the_record_id_and_hash(self):
        other = context.base_packet(user_pressure=0.9)
        self.assertNotEqual(make_record()["signals_hash"], make_record(signals=other)["signals_hash"])
        self.assertNotEqual(make_record()["record_id"], make_record(signals=other)["record_id"])

    def test_changing_the_stage_changes_the_record_id(self):
        self.assertNotEqual(make_record()["record_id"], make_record(stage="evaluate")["record_id"])


class TestAppend(unittest.TestCase):
    def test_append_and_read_round_trip(self):
        with context.scratch_dir() as tmp:
            path = Path(tmp) / "logs" / "cds.jsonl"
            append_record(path, make_record())
            append_record(path, make_record(stage="evaluate"))
            records = read_records(path)
            self.assertEqual([record["stage"] for record in records], ["detect", "evaluate"])

    def test_one_record_per_line(self):
        with context.scratch_dir() as tmp:
            path = Path(tmp) / "cds.jsonl"
            append_record(path, make_record())
            append_record(path, make_record())
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            for line in lines:
                json.loads(line)

    def test_reading_a_missing_log_is_empty_not_an_error(self):
        with context.scratch_dir() as tmp:
            self.assertEqual(read_records(Path(tmp) / "nope.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
