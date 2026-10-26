from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_local_preview"))
import prepare_qa_preview  # noqa: E402


class PrepareQaPreviewTests(unittest.TestCase):
    def test_target_date_builds_three_jst_service_days_in_qa_only_directory(self):
        calls = []

        def fake_prepare(**kwargs):
            calls.append(kwargs)
            return {
                "output": kwargs["output"],
                "service_dates": [date(2026, 10, day) for day in (26, 27, 28)],
                "payload_count": 8,
                "payload_bytes": 123,
                "generation_seconds": 1.0,
                "validation_seconds": 0.5,
            }

        result = prepare_qa_preview.generate("2026-10-27", prepare=fake_prepare)
        self.assertEqual(result["output"], prepare_qa_preview.QA_ROOT / "2026-10-27" / "site")
        self.assertNotEqual(result["output"], prepare_qa_preview.prepare_preview.OUTPUT)
        self.assertEqual([day.isoformat() for day in result["service_dates"]],
                         ["2026-10-26", "2026-10-27", "2026-10-28"])
        self.assertEqual(calls[0]["now"].isoformat(), "2026-10-27T12:00:00+09:00")
        self.assertEqual(calls[0]["output"], result["output"])

    def test_qa_validator_uses_target_jst_date(self):
        def fake_prepare(**kwargs):
            with patch.object(prepare_qa_preview.subprocess, "run", return_value="ok") as run:
                outcome = kwargs["validator"](["node", "validate_payload.mjs", "payload.json"], check=True)
            run.assert_called_once_with(
                ["node", "validate_payload.mjs", "payload.json", "--now", "2026-10-27T12:00:00+09:00"],
                check=True,
            )
            return {
                "output": kwargs["output"],
                "service_dates": [date(2026, 10, day) for day in (26, 27, 28)],
            }

        prepare_qa_preview.generate("2026-10-27", prepare=fake_prepare)

    def test_invalid_target_date_does_not_start_generation(self):
        calls = []
        with self.assertRaises(ValueError):
            prepare_qa_preview.generate("2026-02-30", prepare=lambda **kwargs: calls.append(kwargs))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
