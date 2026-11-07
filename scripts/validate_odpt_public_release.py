#!/usr/bin/env python3
"""Read-only independent validator for v2 release data (not a deployable site)."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import sys

sys.dont_write_bytecode = True
import odpt_release_contract as c


def validate_artifact(root, *, candidate, source, approval, expected_candidate_digest, expected_source_fingerprint, now=None):
    root = c.safe_path(root)
    c.require(root.is_dir(), "artifact_missing")
    raw = c.read_file(root / "manifest.json")
    manifest = c.load_json(raw)
    c.require(c.canonical(manifest) == raw, "manifest_not_canonical")
    if now is not None:
        c.require(isinstance(manifest, dict) and manifest.get("metadata", {}).get("evidenceKind") == "synthetic",
                  "test_clock_requires_synthetic")
    c.validate_manifest(manifest, now)
    meta = manifest["metadata"]
    request = c.load_json(c.read_file(approval))
    c.exact(request, {"candidateDigest", "sourceFingerprint", "applicationPeriod", "approval",
                      "codeCommit", "retrievedAt", "attribution", "evidenceKind"})
    c.require(all(meta[key] == value for key, value in request.items()), "approval_input_mismatch")
    c.hash_value(expected_candidate_digest)
    c.hash_value(expected_source_fingerprint)
    c.require(meta["candidateDigest"] == expected_candidate_digest, "candidate_digest_mismatch")
    c.require(meta["sourceFingerprint"] == expected_source_fingerprint, "source_fingerprint_mismatch")
    entries, info = c.qa._inventory(c.safe_path(source))
    c.require(entries == meta["sourceFiles"], "source_files_mismatch")
    c.require(meta["feed"] == {"version": info["gtfs"]["feedVersion"], "validFrom": info["gtfs"]["validFrom"],
                               "validThrough": info["gtfs"]["validThrough"]}, "source_feed_mismatch")
    # Independently bind the output to the unchanged approved candidate, not
    # merely to the builder's declaration of its digest.
    candidate = c.safe_path(candidate)
    c.require(c.candidate_digest(candidate) == expected_candidate_digest, "candidate_digest_mismatch")
    original = c.load_json(c.read_file(candidate / "private-generator-manifest.json"))
    c.require(original.get("publicationApproved") is False and original.get("applicationPeriod") is None,
              "candidate_must_remain_unapproved")
    c.v2.validate_bundle(candidate, original, list(c.STATION_FILES), manifest["serviceDates"], expected_source_fingerprint)
    c.require(original.get("sourceFiles") == meta["sourceFiles"], "source_files_mismatch")
    release = manifest["releaseId"]
    expected = {"manifest.json", *(f"releases/{release}/{name}" for name in c.STATION_FILES.values())}
    expected_dirs = {"releases", f"releases/{release}"}
    files = {}
    dirs = set()
    for path in root.rglob("*"):
        c.safe_path(path)
        name = path.relative_to(root).as_posix()
        if path.is_dir():
            dirs.add(name)
        else:
            c.require(name in expected, "unexpected_file")
            files[name] = c.read_file(path)
    c.require(set(files) == expected and dirs == expected_dirs, "artifact_tree_invalid")
    c.require(sum(map(len, files.values())) <= c.MAX_TOTAL_BYTES, "artifact_oversize")
    payloads = {station: c.validate_envelope(files[f"releases/{release}/{name}"], manifest, station)
                for station, name in c.STATION_FILES.items()}
    c.require(len({p["generatedAt"] for p in payloads.values()}) == 1, "generated_at_mismatch")
    generated = c.timestamp(next(iter(payloads.values()))["generatedAt"])
    c.require(c.timestamp(meta["retrievedAt"]) <= generated <= c.timestamp(meta["approval"]["approvedAt"]),
              "generation_approval_time_mismatch")
    c.validate_quality(meta["quality"], payloads, manifest["serviceDates"])
    for station, filename in c.v2.ROUTE_FILENAMES.items():
        original_payload = c.load_json(c.read_file(candidate / "public-candidates" / filename))
        c.require(original_payload == payloads[station], "candidate_payload_mismatch")
    q = meta["quality"]
    odpt = original["odpt0"]
    c.require(q["resolution"] == odpt["resolution"]
              and q["stationDateResolution"] == odpt["stationDateResolution"]
              and q["exclusionAudit"] == original["quality"]["exclusionAudit"]
              and q["status"] == odpt["status"]
              and q["unmatchedOriginal"] == odpt["unmatchedOdptJourneyCount"]
              and q["warningOriginal"] == odpt["diagnosticSeverity"]["WARNING"]["codeOccurrences"]
              and q["failGateCount"] == odpt["diagnosticSeverity"]["FAIL"]["failGateCount"]
              and q["odptMatchStatusCounts"] == original["quality"]["odptMatchStatusCounts"], "candidate_quality_mismatch")
    c.require(c.candidate_digest(candidate) == expected_candidate_digest, "candidate_changed")
    c.require(c.qa._inventory(c.safe_path(source))[0] == entries, "source_changed")
    return {"releaseId": release, "artifactKind": c.KIND, "stationCount": 8,
            "serviceDates": manifest["serviceDates"], "bytes": sum(map(len, files.values())),
            "evidenceKind": meta["evidenceKind"], "deployable": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--expected-candidate-digest", required=True)
    parser.add_argument("--expected-source-fingerprint", required=True)
    args = parser.parse_args()
    try:
        result = validate_artifact(args.artifact, candidate=args.candidate, source=args.source, approval=args.approval,
                                   expected_candidate_digest=args.expected_candidate_digest,
                                   expected_source_fingerprint=args.expected_source_fingerprint)
        print(c.canonical(result).decode())
        return 0
    except (ValueError, OSError, KeyError, TypeError, c.v2.V2Error, c.qa.QAError):
        print("v2 release data validation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
