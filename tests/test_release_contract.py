from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release_contract as contract  # noqa: E402
import synthetic_public_fixture_factory as fixtures  # noqa: E402


DATES = ["2026-10-26", "2026-10-27", "2026-10-28"]
RELEASE = "r1-" + "a" * 64


def all_payloads():
    return {station: fixtures.make_public_fixture(station, DATES) for station in contract.STATION_FILES}


def envelopes_and_manifest():
    payloads = all_payloads()
    encoded = {station: json.dumps(contract.create_envelope(release_id=RELEASE, station_id=station,
                payload=payload), ensure_ascii=False, separators=(",", ":")).encode()
               for station, payload in payloads.items()}
    manifest = contract.create_manifest(
        release_id=RELEASE, published_at="2026-10-28T02:15:00Z", generated_at="2026-10-26T00:00:00+09:00",
        service_date_range={"from": DATES[0], "through": DATES[-1]},
        feed={"version": "synthetic-feed-v1", "validFrom": DATES[0], "validThrough": DATES[-1], "sourceUpdatedAt": None},
        application_period={"startsAt": "2026-10-26T00:00:00+09:00", "endsAt": "2026-10-29T00:00:00+09:00"},
        station_json_bytes=encoded)
    return payloads, encoded, manifest


class ReleaseContractTests(unittest.TestCase):
    def test_rfc8785_number_unicode_and_key_order_vectors(self):
        value = {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
                 "string": "€$\u000f\nA'B\"\\", "literals": [None, True, False]}
        expected = b'{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"\xe2\x82\xac$\\u000f\\nA\'B\\\"\\\\"}'
        self.assertEqual(contract.canonicalize_jcs(value), expected)
        scalar_vs_utf16 = {"\ue000": 1, "\U00010000": 2}
        self.assertEqual(contract.canonicalize_jcs(scalar_vs_utf16), b'{"\xf0\x90\x80\x80":2,"\xee\x80\x80":1}')
        self.assertEqual(contract.canonicalize_jcs({"z": 1, "a": 2}), contract.canonicalize_jcs({"a": 2, "z": 1}))

    def test_jcs_rejects_non_json_or_non_interoperable_numbers(self):
        for value in (float("nan"), float("inf"), 9007199254740992, "\ud800", {1: "bad"}):
            with self.subTest(value=repr(value)), self.assertRaises(contract.ReleaseContractError):
                contract.canonicalize_jcs(value)

    def test_descriptor_and_release_id_are_reproducible_and_content_addressed(self):
        inputs = {"runtime_contract": contract.RUNTIME_CONTRACT, "builder_contract_version": "public-builder-v1",
                  "payloads": all_payloads(), "assets": {"index.html": b"<html>", "styles.css": b"a{}", "app.js": b"export {};"}}
        first = contract.build_release_descriptor(**inputs)
        second_inputs = dict(inputs)
        second_inputs["payloads"] = dict(reversed(list(inputs["payloads"].items())))
        second_inputs["assets"] = dict(reversed(list(inputs["assets"].items())))
        second = contract.build_release_descriptor(**second_inputs)
        self.assertEqual(first, second)
        self.assertEqual(contract.calculate_release_id(first), contract.calculate_release_id(second))
        changed_payloads = deepcopy(inputs["payloads"])
        changed_payloads["Hikawadai"]["webApp"]["builtAt"] = "2026-10-28T02:16:00Z"
        self.assertNotEqual(contract.calculate_release_id(first), contract.calculate_release_id(
            contract.build_release_descriptor(**{**inputs, "payloads": changed_payloads})))
        self.assertNotEqual(contract.calculate_release_id(first), contract.calculate_release_id(
            contract.build_release_descriptor(**{**inputs, "runtime_contract": "dotchi-public-runtime-v3"})))
        self.assertNotEqual(contract.calculate_release_id(first), contract.calculate_release_id(
            contract.build_release_descriptor(**{**inputs, "assets": {**inputs["assets"], "app.js": b"other"}})))

    def test_descriptor_binds_exactly_eight_valid_station_payloads_and_assets(self):
        inputs = {"runtime_contract": contract.RUNTIME_CONTRACT, "builder_contract_version": "v1",
                  "payloads": all_payloads(), "assets": {"index.html": b"x"}}
        bad = dict(inputs, payloads={key: value for key, value in inputs["payloads"].items() if key != "Wakoshi"})
        with self.assertRaisesRegex(contract.ReleaseContractError, "exactly"):
            contract.build_release_descriptor(**bad)
        with self.assertRaises(contract.ReleaseContractError):
            contract.build_release_descriptor(**dict(inputs, assets={"../app.js": b"bad"}))

    def test_manifest_generation_and_validation_for_exact_eight_station_set(self):
        _, _, manifest = envelopes_and_manifest()
        self.assertIs(contract.validate_manifest(manifest), manifest)
        self.assertEqual(set(manifest["stations"]), set(contract.STATION_FILES))
        for mutate, code in (
            (lambda m: m["stations"].pop("Wakoshi"), "station_set"),
            (lambda m: m["stations"]["Wakoshi"].update(url=m["stations"]["Kanamecho"]["url"]), "invalid_url"),
            (lambda m: m["stations"]["Wakoshi"].update(url="https://evil.example/x"), "invalid_url"),
            (lambda m: m["stations"]["Wakoshi"].update(url=f"/releases/{RELEASE}/../x"), "invalid_url"),
            (lambda m: m["stations"]["Wakoshi"].update(sha256="bad"), "invalid_hash"),
            (lambda m: m["stations"]["Wakoshi"].update(bytes=True), "invalid_byte_count"),
            (lambda m: m.update(schemaVersion=2), "manifest_schema"),
            (lambda m: m.update(releaseId="r1-nope"), "invalid_release_id"),
            (lambda m: m.update(runtimeContract="unknown"), "compatibility_mismatch"),
            (lambda m: m.update(unexpected=True), "manifest_fields"),
        ):
            changed = deepcopy(manifest)
            mutate(changed)
            with self.subTest(code=code), self.assertRaises(contract.ReleaseContractError) as caught:
                contract.validate_manifest(changed)
            self.assertEqual(caught.exception.code, code)

    def test_common_metadata_must_match_manifest_and_canonical_encoders_are_stable(self):
        payloads = all_payloads()
        payload = payloads["Hikawadai"]
        canonical_envelope = contract.encode_envelope(release_id=RELEASE, station_id="Hikawadai", payload=payload)
        self.assertEqual(contract.canonicalize_jcs(json.loads(canonical_envelope)), canonical_envelope)
        _, _, manifest = envelopes_and_manifest()
        self.assertEqual(contract.encode_manifest(manifest), contract.canonicalize_jcs(manifest))
        altered_payload = deepcopy(payload)
        altered_payload["generatedAt"] = "2026-10-27T00:00:00+09:00"
        altered = contract.encode_envelope(release_id=RELEASE, station_id="Hikawadai", payload=altered_payload)
        with self.assertRaises(contract.ReleaseContractError) as caught:
            contract.create_manifest(release_id=RELEASE, published_at=manifest["publishedAt"],
                generated_at=manifest["generatedAt"], service_date_range=manifest["serviceDateRange"],
                feed=manifest["feed"], application_period=manifest["applicationPeriod"],
                station_json_bytes={**{s: contract.encode_envelope(release_id=RELEASE, station_id=s, payload=p)
                    for s, p in payloads.items()}, "Hikawadai": altered})
        self.assertEqual(caught.exception.code, "manifest_payload_mismatch")

    def test_envelope_and_raw_byte_hash_length_validation(self):
        _, encoded, manifest = envelopes_and_manifest()
        raw = encoded["Hikawadai"]
        verified = contract.verify_station_bytes(raw, manifest, "Hikawadai")
        self.assertEqual(verified["stationId"], "Hikawadai")
        record = manifest["stations"]["Hikawadai"]
        checks = [
            (raw[:-1], manifest["releaseId"], "Hikawadai", record["sha256"], record["bytes"], "byte_count_mismatch"),
            (raw, "r1-" + "b" * 64, "Hikawadai", record["sha256"], record["bytes"], "release_id_mismatch"),
            (raw, manifest["releaseId"], "Senkawa", record["sha256"], record["bytes"], "station_mismatch"),
            (raw, manifest["releaseId"], "Hikawadai", "0" * 64, record["bytes"], "hash_mismatch"),
        ]
        for args in checks:
            with self.subTest(code=args[-1]), self.assertRaises(contract.ReleaseContractError) as caught:
                contract.verify_envelope_bytes(args[0], expected_release_id=args[1], expected_station_id=args[2],
                    expected_sha256=args[3], expected_bytes=args[4])
            self.assertEqual(caught.exception.code, args[-1])
        for bad in (b"{", b"{}"):
            with self.subTest(raw=bad), self.assertRaises(contract.ReleaseContractError):
                contract.verify_envelope_bytes(bad, expected_release_id=manifest["releaseId"], expected_station_id="Hikawadai",
                    expected_sha256=contract.sha256_hex(bad), expected_bytes=len(bad))

    def test_inner_payload_invalid_and_duplicate_json_are_rejected(self):
        payload = all_payloads()["Hikawadai"]
        envelope = contract.create_envelope(release_id=RELEASE, station_id="Hikawadai", payload=payload)
        envelope["payload"]["unexpected"] = "no"
        raw = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()
        with self.assertRaises(contract.ReleaseContractError) as caught:
            contract.verify_envelope_bytes(raw, expected_release_id=RELEASE, expected_station_id="Hikawadai",
                expected_sha256=contract.sha256_hex(raw), expected_bytes=len(raw))
        self.assertEqual(caught.exception.code, "invalid_payload")
        duplicate = b'{"schemaVersion":1,"schemaVersion":1}'
        with self.assertRaises(contract.ReleaseContractError) as caught:
            contract.verify_envelope_bytes(duplicate, expected_release_id=RELEASE, expected_station_id="Hikawadai",
                expected_sha256=contract.sha256_hex(duplicate), expected_bytes=len(duplicate))
        self.assertEqual(caught.exception.code, "invalid_json")


if __name__ == "__main__":
    unittest.main()
