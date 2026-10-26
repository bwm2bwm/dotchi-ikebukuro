from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_local_preview"))
import prepare_preview  # noqa: E402


class PreparePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / "source"
        self.source.mkdir()
        for name in prepare_preview.PREVIEW_FILES:
            (self.source / name).write_text(name)
        (self.source / "validate_payload.mjs").write_text("fixture")
        self.adapter, self.loader, self.exporter_path = (base / "adapter", base / "loader", base / "exporter")
        for path in (self.adapter, self.loader, self.exporter_path):
            path.write_text("fixture")
        self.output = base / "persistent" / "site"
        self.output.mkdir(parents=True)
        (self.output / "old.marker").write_text("keep")
        self.inputs = [base / f"input-{index}" for index in range(4)]
        for path in self.inputs:
            path.write_text("fixture")
        self.patches = [
            patch.object(prepare_preview, "SOURCE", self.source),
            patch.object(prepare_preview, "ADAPTER", self.adapter),
            patch.object(prepare_preview, "LOADER", self.loader),
            patch.object(prepare_preview, "EXPORTER", self.exporter_path),
            patch.object(prepare_preview, "REQUIRED_INPUTS", tuple(self.inputs)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def successful_exporter(self, command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.write_text('{"fixture":true}')

    @staticmethod
    def successful_validator(command, **kwargs):
        assert Path(command[-1]).is_file()

    def test_normal_update_stages_and_replaces_preview(self):
        exported = []
        validated = []
        def exporter(command, **kwargs):
            exported.append(command)
            self.successful_exporter(command, **kwargs)
        def validator(command, **kwargs):
            validated.append(command[-1])
            self.successful_validator(command, **kwargs)
        started_at = time.time()
        result = prepare_preview.prepare(now=datetime(2026, 10, 23, 0, 10, tzinfo=ZoneInfo("Asia/Tokyo")),
                                        output=self.output, exporter=exporter, validator=validator)
        self.assertEqual([str(x) for x in result["service_dates"]], ["2026-10-22", "2026-10-23", "2026-10-24"])
        self.assertFalse((self.output / "old.marker").exists())
        self.assertTrue((self.output / "timetable.json").exists())
        self.assertEqual(result["payload_count"], 8)
        self.assertEqual(result["payload_bytes"], sum((self.output / name).stat().st_size
                                                       for name in prepare_preview.DESTINATION_PAYLOADS.values()))
        self.assertGreaterEqual(result["generation_seconds"], 0)
        self.assertGreaterEqual(result["validation_seconds"], 0)
        self.assertEqual(len(exported), 8)
        self.assertEqual(len(validated), 8)
        self.assertEqual({command[command.index("--destination-station-id") + 1] for command in exported},
                         set(prepare_preview.DESTINATION_PAYLOADS))
        self.assertEqual({Path(command[command.index("--output") + 1]).name for command in exported},
                         set(prepare_preview.DESTINATION_PAYLOADS.values()))
        self.assertEqual((self.output / "styles.css").read_bytes(), (ROOT / "styles.css").read_bytes())
        self.assertEqual((self.output / "index.html").read_text(), "index.html")
        self.assertEqual((self.output / "preview_core.mjs").read_text(), "preview_core.mjs")
        self.assertEqual((self.output / "terminal_ui.mjs").read_text(), "terminal_ui.mjs")
        self.assertEqual((self.output / "virtual_now.mjs").read_text(), "virtual_now.mjs")
        self.assertEqual((self.output / "performance_metrics.mjs").read_text(), "performance_metrics.mjs")
        self.assertEqual((self.output / "preview_diagnostics.css").read_text(), "preview_diagnostics.css")
        self.assertGreaterEqual((self.output / "preview.js").stat().st_mtime, started_at)

    def test_failure_while_generating_one_destination_keeps_existing_preview(self):
        calls = 0
        def fail_seventh(command, **kwargs):
            nonlocal calls
            calls += 1
            output = Path(command[command.index("--output") + 1])
            output.write_text("complete payload" if calls < 7 else "partial payload")
            if calls == 7:
                raise RuntimeError("seventh destination failed")
        with self.assertRaisesRegex(RuntimeError, "seventh destination"):
            prepare_preview.prepare(output=self.output, exporter=fail_seventh,
                                    validator=self.successful_validator)
        self.assertEqual((self.output / "old.marker").read_text(), "keep")
        self.assertFalse(any(self.output.glob("timetable-*.json")))

    def test_validation_failure_on_one_destination_keeps_existing_preview(self):
        calls = 0
        def reject_seventh(command, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 7:
                raise RuntimeError("seventh payload invalid")
            self.successful_validator(command, **kwargs)
        with self.assertRaisesRegex(RuntimeError, "seventh payload invalid"):
            prepare_preview.prepare(output=self.output, exporter=self.successful_exporter, validator=reject_seventh)
        self.assertEqual((self.output / "old.marker").read_text(), "keep")
        self.assertFalse(any(self.output.glob("timetable-*.json")))

    def test_missing_required_file_fails_before_changing_output(self):
        self.inputs[0].unlink()
        with self.assertRaises(FileNotFoundError):
            prepare_preview.prepare(output=self.output)
        self.assertEqual((self.output / "old.marker").read_text(), "keep")

    def test_invalid_payload_or_missing_metadata_keeps_existing_preview(self):
        def reject(command, **kwargs):
            raise RuntimeError("invalid payload metadata")
        with self.assertRaisesRegex(RuntimeError, "metadata"):
            prepare_preview.prepare(output=self.output, exporter=self.successful_exporter, validator=reject)
        self.assertEqual((self.output / "old.marker").read_text(), "keep")

    def test_missing_service_day_keeps_existing_preview(self):
        def reject(command, **kwargs):
            raise RuntimeError("missing_service_days")
        with self.assertRaisesRegex(RuntimeError, "missing_service_days"):
            prepare_preview.prepare(output=self.output, exporter=self.successful_exporter, validator=reject)
        self.assertEqual((self.output / "old.marker").read_text(), "keep")

    def test_export_exception_after_partial_write_keeps_existing_preview(self):
        def fail(command, **kwargs):
            Path(command[command.index("--output") + 1]).write_text("partial")
            raise RuntimeError("mid-update")
        with self.assertRaisesRegex(RuntimeError, "mid-update"):
            prepare_preview.prepare(output=self.output, exporter=fail, validator=self.successful_validator)
        self.assertEqual((self.output / "old.marker").read_text(), "keep")

    def test_failed_final_swap_restores_existing_preview(self):
        def fail_stage_move(src, dst):
            if Path(src).name == "site":
                raise OSError("simulated final swap failure")
            os.replace(src, dst)
        with self.assertRaisesRegex(OSError, "final swap"):
            prepare_preview.prepare(output=self.output, exporter=self.successful_exporter,
                                    validator=self.successful_validator, replace=fail_stage_move)
        self.assertEqual((self.output / "old.marker").read_text(), "keep")

    def test_midnight_date_rollover(self):
        days = prepare_preview.service_dates(datetime(2026, 10, 24, 0, 1, tzinfo=ZoneInfo("Asia/Tokyo")))
        self.assertEqual([day.isoformat() for day in days], ["2026-10-23", "2026-10-24", "2026-10-25"])


if __name__ == "__main__":
    unittest.main()
