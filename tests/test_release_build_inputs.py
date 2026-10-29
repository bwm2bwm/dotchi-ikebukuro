from datetime import datetime, timezone
import unittest

from scripts.validate_release_build_inputs import (
    BuildInputError,
    compare_release_ids,
    resolve_build_inputs,
)


RELEASE_A = "r1-" + "a" * 64
RELEASE_B = "r1-" + "b" * 64


class ReleaseBuildInputTests(unittest.TestCase):
    def test_explicit_canonical_service_date_is_kept(self):
        result = resolve_build_inputs(service_date="2026-10-30",
            expected_previous_release_id=RELEASE_A, publish_staging=False,
            allow_initial_legacy_migration=False)
        self.assertEqual(result["service_date_anchor"], "2026-10-30")
        self.assertEqual(result["expected_previous_release_id"], RELEASE_A)

    def test_omitted_service_date_preserves_jst_today_behavior(self):
        result = resolve_build_inputs(service_date="", expected_previous_release_id=None,
            publish_staging=False, allow_initial_legacy_migration=False,
            now=datetime(2026, 10, 29, 15, 30, tzinfo=timezone.utc))
        self.assertEqual(result["service_date_anchor"], "2026-10-30")

    def test_invalid_calendar_and_noncanonical_dates_fail_closed(self):
        for value in ("2026-02-30", "2026-1-01", "2026-01-01\n", "2026/01/01"):
            with self.subTest(value=value), self.assertRaises(BuildInputError):
                resolve_build_inputs(service_date=value, expected_previous_release_id=None,
                    publish_staging=False, allow_initial_legacy_migration=False)

    def test_expected_release_id_must_be_r1_sha256(self):
        with self.assertRaises(BuildInputError):
            resolve_build_inputs(service_date="2026-10-30",
                expected_previous_release_id="r1-" + "A" * 64,
                publish_staging=False, allow_initial_legacy_migration=False)

    def test_release_managed_publish_requires_expected_previous_release(self):
        with self.assertRaises(BuildInputError):
            resolve_build_inputs(service_date="2026-10-30", expected_previous_release_id=None,
                publish_staging=True, allow_initial_legacy_migration=False)

    def test_initial_legacy_migration_is_explicit_and_has_no_expected_release(self):
        result = resolve_build_inputs(service_date="", expected_previous_release_id=None,
            publish_staging=True, allow_initial_legacy_migration=True)
        self.assertIsNone(result["expected_previous_release_id"])

    def test_release_managed_publish_with_expected_release_and_legacy_flag_off_is_allowed(self):
        result = resolve_build_inputs(service_date="2026-10-30",
            expected_previous_release_id=RELEASE_A, publish_staging=True,
            allow_initial_legacy_migration=False)
        self.assertEqual(result["expected_previous_release_id"], RELEASE_A)

    def test_expected_release_and_legacy_migration_flag_conflict_fails_closed_at_build_time(self):
        for publish_staging in (False, True):
            with self.subTest(publish_staging=publish_staging), self.assertRaises(BuildInputError):
                resolve_build_inputs(service_date="2026-10-30",
                    expected_previous_release_id=RELEASE_A, publish_staging=publish_staging,
                    allow_initial_legacy_migration=True)

    def test_equal_release_ids_fail_and_different_ids_pass(self):
        with self.assertRaises(BuildInputError):
            compare_release_ids(built_release_id=RELEASE_A,
                expected_previous_release_id=RELEASE_A)
        self.assertEqual(compare_release_ids(built_release_id=RELEASE_B,
            expected_previous_release_id=RELEASE_A), "different")
        self.assertEqual(compare_release_ids(built_release_id=RELEASE_B,
            expected_previous_release_id=None), "not-requested")


if __name__ == "__main__":
    unittest.main()
