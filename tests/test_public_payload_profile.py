from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_payload_profile import (  # noqa: E402
    LOCAL_DATA_SCOPE,
    PUBLIC_DATA_SCOPE,
    PublicPayloadProfileError,
    project_public_payload,
    validate_public_payload,
)


FIXTURE = ROOT / "tests" / "fixtures" / "public_payload_profile_input.json"


def synthetic_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class PublicPayloadProfileTests(unittest.TestCase):
    def test_public_validation_reuses_allowlist_and_rejects_unknown_fields(self):
        public = project_public_payload(synthetic_payload())
        self.assertIs(validate_public_payload(public), public)

        public["apiKey"] = "synthetic-secret-sentinel"
        with self.assertRaisesRegex(PublicPayloadProfileError, "unknown field"):
            validate_public_payload(public)

        public = project_public_payload(synthetic_payload())
        public["dataScope"] = LOCAL_DATA_SCOPE
        with self.assertRaisesRegex(PublicPayloadProfileError, "public-display-v1 input required"):
            validate_public_payload(public)

    def test_projects_only_allowlisted_schema_and_preserves_adapter_fields(self):
        projected = project_public_payload(synthetic_payload())

        self.assertEqual(projected["schemaVersion"], 1)
        self.assertEqual(projected["dataScope"], PUBLIC_DATA_SCOPE)
        self.assertEqual(projected["timezone"], "Asia/Tokyo")
        self.assertEqual(projected["serviceDays"][0]["serviceDate"], "2026-10-26")
        self.assertEqual(projected["serviceDays"][1]["serviceDate"], "2026-10-27")
        self.assertEqual(projected["serviceDays"][1]["departures"][0]["departureServiceSeconds"], 93000)
        self.assertEqual(projected["serviceDays"][1]["departures"][0]["departureText"], "25:50:00")
        self.assertEqual(projected["serviceDays"][0]["destinationStatus"]["routes"]["6"]["candidateCount"], 1)
        self.assertEqual(projected["serviceDays"][0]["destinationStatus"]["routes"]["9"]["directCandidateCount"], 0)
        self.assertEqual(projected["serviceDays"][1]["destinationStatus"]["routes"]["9"]["originTripCount"], 1)

        departure = projected["serviceDays"][0]["departures"][0]
        self.assertEqual(departure["id"], "synthetic:trip-a:1")
        self.assertEqual(departure["originTripId"], "synthetic-trip-a")
        self.assertEqual(departure["primary"]["kind"], "direct")
        self.assertEqual(departure["directAlternative"]["arrivalServiceSeconds"], 22800)
        transfer = departure["bestTransferAlternative"]
        self.assertEqual(transfer["kind"], "transfer")
        self.assertEqual(transfer["transfer"]["waitSeconds"], 120)
        self.assertEqual(transfer["transfer"]["outgoingRouteId"], "9")
        self.assertIn("dataQuality", departure)

        serialized = json.dumps(projected, ensure_ascii=False)
        for forbidden in ("apiKey", "synthetic-secret", "localAbsolutePath", "/synthetic/private",
                          "internalLog", "internalDiagnostic", "futureUnknownField", "odptTrainTypeUri",
                          "outgoingOdptTrainTypeUri", "typeDiagnostic", "stopPatternStates"):
            self.assertNotIn(forbidden, serialized)

    def test_input_is_not_mutated_and_projection_is_deterministic(self):
        payload = synthetic_payload()
        before = copy.deepcopy(payload)

        first = project_public_payload(payload)
        second = project_public_payload(payload)

        self.assertEqual(payload, before)
        self.assertEqual(first, second)
        self.assertIsNot(first, payload)
        self.assertIsNot(first["serviceDays"], payload["serviceDays"])
        self.assertIsNot(first["serviceDays"][0]["departures"][0],
                         payload["serviceDays"][0]["departures"][0])

    def test_unknown_fields_are_dropped_at_each_level(self):
        payload = synthetic_payload()
        projected = project_public_payload(payload)

        self.assertEqual(set(projected), {
            "schemaVersion", "dataScope", "generatedAt", "timezone", "feed", "odpt",
            "applicationPeriod", "webApp", "connectionPolicy", "serviceDays", "excludedServiceDates",
        })
        self.assertEqual(set(projected["feed"]), {"version", "validFrom", "validThrough", "sourceUpdatedAt"})
        self.assertNotIn("terminalDiagnostic", projected["serviceDays"][0])
        self.assertNotIn("diagnostic", projected["serviceDays"][0]["destinationStatus"])
        self.assertNotIn("apiKey", projected["serviceDays"][0]["departures"][0]["bestTransferAlternative"]["transfer"])

    def test_inconsistent_destination_status_counts_are_rejected(self):
        payload = synthetic_payload()
        payload["serviceDays"][0]["destinationStatus"]["candidateCount"] = 0
        with self.assertRaisesRegex(PublicPayloadProfileError, "must match departures"):
            project_public_payload(payload)

    def test_empty_service_data_is_rejected(self):
        payload = synthetic_payload()
        payload["serviceDays"] = []
        with self.assertRaisesRegex(PublicPayloadProfileError, "nonempty array"):
            project_public_payload(payload)

        payload = synthetic_payload()
        for day in payload["serviceDays"]:
            day["departures"] = []
            day.pop("destinationStatus")
        with self.assertRaisesRegex(PublicPayloadProfileError, "at least one departure"):
            project_public_payload(payload)

    def test_malformed_required_values_are_rejected(self):
        cases = []

        payload = synthetic_payload()
        del payload["serviceDays"][0]["departures"][0]["originTripId"]
        cases.append((payload, "originTripId"))

        payload = synthetic_payload()
        payload["serviceDays"][0]["serviceDate"] = "2026-02-30"
        cases.append((payload, "serviceDate"))

        payload = synthetic_payload()
        payload["serviceDays"][1]["departures"][0]["departureServiceSeconds"] = -1
        cases.append((payload, "departureServiceSeconds"))

        payload = synthetic_payload()
        payload["serviceDays"][0]["departures"][0]["bestTransferAlternative"]["transfer"]["waitSeconds"] = 0
        cases.append((payload, "waitSeconds"))

        payload = synthetic_payload()
        del payload["serviceDays"][0]["destinationStatus"]["routes"]["9"]["directCandidateCount"]
        cases.append((payload, "directCandidateCount"))

        for payload, expected in cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(PublicPayloadProfileError, expected):
                project_public_payload(payload)

    def test_local_and_public_profiles_cannot_be_confused(self):
        payload = synthetic_payload()
        self.assertEqual(payload["dataScope"], LOCAL_DATA_SCOPE)

        payload["dataScope"] = PUBLIC_DATA_SCOPE
        with self.assertRaisesRegex(PublicPayloadProfileError, "local-preview-only input required"):
            project_public_payload(payload)

        payload = synthetic_payload()
        payload["dataScope"] = "other-profile"
        with self.assertRaisesRegex(PublicPayloadProfileError, "local-preview-only input required"):
            project_public_payload(payload)

    def test_duplicate_service_date_and_mixed_destinations_are_rejected(self):
        payload = synthetic_payload()
        payload["serviceDays"][1]["serviceDate"] = payload["serviceDays"][0]["serviceDate"]
        with self.assertRaisesRegex(PublicPayloadProfileError, "duplicate service date"):
            project_public_payload(payload)

        payload = synthetic_payload()
        payload["serviceDays"][1]["destinationStationId"] = "Wakoshi"
        with self.assertRaisesRegex(PublicPayloadProfileError, "destination must be consistent"):
            project_public_payload(payload)


if __name__ == "__main__":
    unittest.main()
