#!/usr/bin/env python3
"""Build v2 release DATA from an unchanged candidate and separate approval input.

This does not build a runnable public site or deploy anything. Approval inputs
are supplied by a human; this tool never creates them or changes a Snapshot.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import copy
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import odpt_release_contract as c
from validate_odpt_public_release import validate_artifact


def inspect_candidate(bundle, source):
    """Read-only preflight; no approval or period is needed or generated."""
    bundle, source = c.safe_path(bundle), c.safe_path(source)
    manifest = c.load_json(c.read_file(bundle / "private-generator-manifest.json"))
    c.require(manifest.get("publicationApproved") is False and manifest.get("applicationPeriod") is None,
              "candidate_must_remain_unapproved")
    entries, info = c.qa._inventory(source)
    fingerprint = c.qa._fingerprint(entries)
    c.require(manifest.get("sourceFiles") == entries, "source_files_mismatch")
    c.validate_sources(entries, fingerprint)
    dates = manifest.get("evaluationServiceDates")
    c.v2.validate_bundle(bundle, manifest, list(c.STATION_FILES), dates, fingerprint)
    quality = extract_quality(manifest)
    payloads = {s: c.load_json(c.read_file(bundle / "public-candidates" / name))
                for s, name in c.v2.ROUTE_FILENAMES.items()}
    c.validate_quality(quality, payloads, dates)
    return manifest, payloads, info, c.candidate_digest(bundle)


def extract_quality(manifest):
    odpt = manifest["odpt0"]
    severity = odpt["diagnosticSeverity"]
    return copy.deepcopy({"status": odpt["status"],
        "failGateCount": severity["FAIL"]["failGateCount"],
        "unmatchedOriginal": odpt["unmatchedOdptJourneyCount"],
        "warningOriginal": severity["WARNING"]["codeOccurrences"],
        "resolution": odpt["resolution"], "stationDateResolution": odpt["stationDateResolution"],
        "exclusionAudit": manifest["quality"]["exclusionAudit"],
        "odptMatchStatusCounts": manifest["quality"]["odptMatchStatusCounts"]})


def build(*, candidate, source, approval, output, now=None):
    candidate, source = c.safe_path(candidate), c.safe_path(source)
    approval = c.safe_path(approval)
    output = c.safe_path(output)
    c.require(not os.path.lexists(output), "output_exists")
    for protected in (c.ROOT, candidate, source):
        c.require(not output.is_relative_to(protected), "output_inside_protected_input")
    c.require(output.parent.is_dir(), "output_parent_missing")
    request = c.load_json(c.read_file(approval))
    c.exact(request, {"candidateDigest", "sourceFingerprint", "applicationPeriod", "approval",
                      "codeCommit", "retrievedAt", "attribution", "evidenceKind"})
    manifest, payloads, info, candidate_hash = inspect_candidate(candidate, source)
    c.require(request["candidateDigest"] == candidate_hash, "candidate_digest_mismatch")
    c.require(request["sourceFingerprint"] == manifest["sourceFingerprint"], "source_fingerprint_mismatch")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=c.ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    c.require(request["codeCommit"] == commit, "code_commit_mismatch")
    meta = {**request, "sourceFiles": manifest["sourceFiles"],
            "feed": {"version": info["gtfs"]["feedVersion"], "validFrom": info["gtfs"]["validFrom"],
                     "validThrough": info["gtfs"]["validThrough"]},
            "quality": extract_quality(manifest), "transferSearchPolicy": manifest["transferSearchPolicy"]}
    if now is not None:
        c.require(request["evidenceKind"] == "synthetic", "test_clock_requires_synthetic")
    now = now or datetime.now(timezone.utc)
    c.validate_metadata(meta, manifest["evaluationServiceDates"], now)
    descriptor = {"manifestSchemaVersion": 2, "jsonEnvelopeSchemaVersion": 1, "payloadSchemaVersion": 2,
        "publicDataScope": c.SCOPE, "runtimeContract": c.RUNTIME,
        "builderContractVersion": "dotchi-odpt-release-builder-v1", "metadataSha256": c.digest(c.canonical(meta)),
        "stations": [{"stationId": s, "payloadSha256": c.digest(c.canonical(payloads[s]))}
                     for s in sorted(c.STATION_FILES)]}
    release = c.release_id(descriptor)
    envelopes = {s: c.canonical({"schemaVersion": 1, "releaseId": release, "stationId": s,
                 "payloadSchemaVersion": 2, "dataScope": c.SCOPE, "payload": payloads[s]}) for s in c.STATION_FILES}
    public = {"schemaVersion": 2, "artifactKind": c.KIND, "releaseId": release,
        "releaseDescriptor": descriptor, "runtimeContract": c.RUNTIME, "payloadSchemaVersion": 2,
        "dataScope": c.SCOPE, "serviceDates": manifest["evaluationServiceDates"], "metadata": meta,
        "retainedReleases": [],
        "stations": {s: {"url": f"/releases/{release}/{c.STATION_FILES[s]}",
                         "sha256": c.digest(raw), "bytes": len(raw)} for s, raw in envelopes.items()}}
    stage = Path(tempfile.mkdtemp(prefix=".odpt-release-", dir=output.parent))
    try:
        (stage / "releases" / release).mkdir(parents=True, mode=0o700)
        (stage / "manifest.json").write_bytes(c.canonical(public))
        for s, raw in envelopes.items():
            (stage / "releases" / release / c.STATION_FILES[s]).write_bytes(raw)
        result = validate_artifact(stage, candidate=candidate, source=source, approval=approval, expected_candidate_digest=candidate_hash,
                                  expected_source_fingerprint=meta["sourceFingerprint"], now=now)
        c.require(c.candidate_digest(candidate) == candidate_hash, "candidate_changed")
        c.require(c.qa._inventory(source)[0] == manifest["sourceFiles"], "source_changed")
        c.require(c.load_json(c.read_file(approval)) == request, "approval_changed")
        os.rename(stage, output)
        return result
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="explicit read-only raw source directory")
    parser.add_argument("--approval", type=Path, required=True, help="separate human-supplied publication input")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(c.canonical(build(candidate=args.candidate, source=args.source,
                                approval=args.approval, output=args.output)).decode())
        return 0
    except (ValueError, OSError, KeyError, TypeError, c.v2.V2Error, c.qa.QAError, subprocess.SubprocessError):
        print("v2 release data build failed; no publication performed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
