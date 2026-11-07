#!/usr/bin/env python3
"""Assemble one v2 full-site from verified release data and fixed public assets.

Local/offline only; does not create publication approvals, retain generations,
or deploy. The input data release and original candidate are never changed.
"""
import argparse
import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import odpt_release_contract as c
from validate_odpt_public_release import validate_artifact as validate_data
from validate_odpt_public_site import validate_artifact as validate_site


def assemble(*, data_release, candidate, source, approval, output, contact_url,
             expected_candidate_digest, expected_source_fingerprint, now=None):
    inputs = {"candidate": c.safe_path(candidate), "source": c.safe_path(source), "approval": c.safe_path(approval),
              "expected_candidate_digest": expected_candidate_digest,
              "expected_source_fingerprint": expected_source_fingerprint, "now": now}
    data_release, output = c.safe_path(data_release), c.safe_path(output)
    c.require(not os.path.lexists(output) and output.parent.is_dir(), "output_exists_or_parent_missing")
    for protected in (c.ROOT, data_release, inputs["candidate"], inputs["source"]):
        c.require(not output.is_relative_to(protected), "output_inside_protected_input")
    validate_data(data_release, **inputs)
    original = c.read_file(data_release / "manifest.json")
    manifest = c.load_json(original)
    payloads = {}
    source_bytes = {}
    for station, record in manifest["stations"].items():
        raw = c.read_file(data_release / record["url"].lstrip("/"))
        source_bytes[station] = raw
        payloads[station] = c.validate_envelope(raw, manifest, station)
    assets = c.site_asset_bytes(contact_url, manifest["metadata"]["evidenceKind"])
    public = copy.deepcopy(manifest)
    descriptor = public["releaseDescriptor"]
    descriptor["builderContractVersion"] = "dotchi-odpt-site-assembler-v1"
    descriptor["assets"] = [{"path": name, "bytes": len(raw), "sha256": c.digest(raw)}
                            for name, raw in sorted(assets.items())]
    release = c.release_id(descriptor)
    public.update(artifactKind=c.SITE_KIND, releaseId=release)
    stage = Path(tempfile.mkdtemp(prefix=".odpt-site-", dir=output.parent))
    try:
        (stage / "releases" / release).mkdir(parents=True, mode=0o700)
        for name, raw in assets.items():
            (stage / name).write_bytes(raw)
        for station, name in c.STATION_FILES.items():
            raw = c.canonical({"schemaVersion": 1, "releaseId": release, "stationId": station,
                "payloadSchemaVersion": 2, "dataScope": c.SCOPE, "payload": payloads[station]})
            relative = f"releases/{release}/{name}"
            (stage / relative).write_bytes(raw)
            public["stations"][station] = {"url": "/" + relative, "bytes": len(raw), "sha256": c.digest(raw)}
        (stage / "manifest.json").write_bytes(c.canonical(public))
        result = validate_site(stage, contact_url=contact_url, **inputs)
        c.require(c.read_file(data_release / "manifest.json") == original, "data_release_changed")
        for station, record in manifest["stations"].items():
            c.require(c.read_file(data_release / record["url"].lstrip("/")) == source_bytes[station], "data_release_changed")
        c.require(not os.path.lexists(output), "output_exists")
        os.rename(stage, output)
        return result
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-release", "candidate", "source", "approval", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--contact-url", required=True)
    parser.add_argument("--expected-candidate-digest", required=True)
    parser.add_argument("--expected-source-fingerprint", required=True)
    args = parser.parse_args()
    try:
        print(c.canonical(assemble(**vars(args))).decode())
        return 0
    except (ValueError, OSError, KeyError, TypeError, c.v2.V2Error, c.qa.QAError, subprocess.SubprocessError):
        print("v2 full-site assembly failed; no publication performed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
