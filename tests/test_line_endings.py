"""Tests that every artefact this skill writes has LF line endings.

The repository claims that identical inputs produce identical results. A run on
Windows that writes CRLF while the same run on Linux writes LF breaks that claim at
the byte level: the log, the state file, the stage outputs and the generated reports
all diverge, and ``.gitattributes`` then hides the divergence by normalising on
commit. These tests pin the property directly.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import context

from cds_config import open_text, write_text
from cds_index import build_detection
from cds_log import append_record, build_record
from cds_state import StateMachine


def assert_lf_only(case: unittest.TestCase, path: Path) -> None:
    data = path.read_bytes()
    case.assertNotIn(b"\r", data, f"{path.name} contains a carriage return")
    case.assertNotIn(b"\xef\xbb\xbf", data, f"{path.name} starts with a BOM")


class TestWriteHelpers(unittest.TestCase):
    def test_write_text_emits_lf(self):
        with context.scratch_dir() as tmp:
            target = tmp / "out.txt"
            write_text(target, "line one\nline two\n")
            self.assertEqual(target.read_bytes(), b"line one\nline two\n")

    def test_write_text_creates_parent_directories(self):
        with context.scratch_dir() as tmp:
            target = tmp / "nested" / "deep" / "out.json"
            write_text(target, "{}\n")
            self.assertTrue(target.exists())

    def test_write_text_never_emits_a_bom(self):
        with context.scratch_dir() as tmp:
            target = tmp / "zh.txt"
            write_text(target, "张力指数\n")
            assert_lf_only(self, target)

    def test_open_text_appends_without_translation(self):
        with context.scratch_dir() as tmp:
            target = tmp / "log.jsonl"
            with open_text(target, "a") as handle:
                handle.write('{"a":1}\n')
            with open_text(target, "a") as handle:
                handle.write('{"b":2}\n')
            self.assertEqual(target.read_bytes(), b'{"a":1}\n{"b":2}\n')


class TestArtefactsAreLf(unittest.TestCase):
    def test_stage_output_is_lf(self):
        with context.scratch_dir() as tmp:
            target = tmp / "detection.json"
            write_text(target, __import__("json").dumps(build_detection(context.base_packet(), context.BASE_CONFIG),
                                                        indent=2, ensure_ascii=False))
            assert_lf_only(self, target)

    def test_log_record_is_lf(self):
        with context.scratch_dir() as tmp:
            log = tmp / "logs" / "cds.jsonl"
            detection = build_detection(context.base_packet(), context.BASE_CONFIG)
            append_record(log, build_record(
                config=context.BASE_CONFIG,
                run_id="test_run",
                turn_id=1,
                stage="detect",
                payload=detection,
                event_id=detection["conflict_event"]["event_id"],
                timestamp="2026-01-01T00:00:00Z",
            ))
            assert_lf_only(self, log)
            self.assertEqual(log.read_bytes().count(b"\n"), 1)

    def test_state_file_is_lf(self):
        with context.scratch_dir() as tmp:
            path = tmp / "state.json"
            machine = StateMachine(context.BASE_CONFIG, "test_run", path)
            machine.advance_turn()
            machine.ingest_detection(build_detection(context.base_packet(), context.BASE_CONFIG))
            machine.save()
            assert_lf_only(self, path)

    def test_shipped_reports_are_lf(self):
        """These are committed, so CRLF would churn the diff on every regeneration."""
        for name in ("report.md", "results.csv", "sensitivity.md"):
            path = context.REPO_ROOT / "eval" / name
            if path.exists():
                with self.subTest(report=name):
                    assert_lf_only(self, path)

    def test_committed_source_files_are_lf(self):
        """`.gitattributes` declares eol=lf, so the working tree should already match."""
        offenders = []
        for pattern in ("*.md", "*.py", "*.json", "*.yml", "*.sh", "*.cff"):
            for path in context.REPO_ROOT.rglob(pattern):
                if any(part in {".git", "__pycache__", ".scratch"} for part in path.parts):
                    continue
                if path.suffix == ".ps1":
                    continue  # .gitattributes pins PowerShell to CRLF on purpose
                if b"\r" in path.read_bytes():
                    offenders.append(str(path.relative_to(context.REPO_ROOT)))
        self.assertEqual(offenders, [], f"these files carry CRLF but must be LF: {offenders}")


if __name__ == "__main__":
    unittest.main()
