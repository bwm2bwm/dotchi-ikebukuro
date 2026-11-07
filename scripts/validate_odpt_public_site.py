#!/usr/bin/env python3
"""Independently validate one current v2 full-site against its approved inputs/toolchain.

No assembly or network calls. Retained v2 generations are deliberately deferred.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
import odpt_release_contract as c
from validate_odpt_public_release import validate_artifact as validate_release
from validate_public_artifact import _HtmlReferences, STATIC_IMPORT_PATTERN


class SiteHtml(_HtmlReferences):
    def __init__(self):
        super().__init__()
        self.contact = []
        self.metas = {}
        self.duplicate_ids = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id") in self.ids:
            self.duplicate_ids = True
        super().handle_starttag(tag, attrs)
        if tag == "meta" and values.get("name"):
            c.require(values["name"] not in self.metas, "duplicate_meta")
            self.metas[values["name"]] = values.get("content")
        if values.get("id") == "publication-contact":
            self.contact.append(values.get("data-contact-url"))


def validate_site_assets(root, manifest, contact_url):
    """Asset records + trusted toolchain bytes + public entry/import graph."""
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=c.ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    c.require(manifest["metadata"]["codeCommit"] == commit, "site_toolchain_commit_mismatch")
    contents = {name: c.read_file(root / name) for name in c.SITE_ASSETS}
    parser = SiteHtml()
    parser.feed(contents["index.html"].decode("utf-8"))
    parser.close()
    c.require(not parser.duplicate_ids and not parser.inline_script and not parser.inline_handler
              and not parser.embedded_document, "public_html_unsafe")
    c.require(parser.scripts == [("preview_public_v2.js", "module")]
              and parser.stylesheets == ["styles.css", "preview.css", "odpt_public.css"], "public_entry_invalid")
    c.require(parser.metas.get("dotchi-data-mode") == "release-managed"
              and parser.metas.get("dotchi-payload-profile") == c.SCOPE, "public_profile_invalid")
    c.require(len(parser.contact) == 1, "contact_missing")
    c.require(parser.contact[0] == contact_url, "contact_input_mismatch")
    expected = c.site_asset_bytes(contact_url, manifest["metadata"]["evidenceKind"])
    records = manifest["releaseDescriptor"]["assets"]
    for row in records:
        raw = contents[row["path"]]
        c.require(len(raw) == row["bytes"] and c.digest(raw) == row["sha256"], "asset_integrity_mismatch")
        c.require(raw == expected[row["path"]], "site_toolchain_asset_mismatch")
    # Exact source equality above also forbids arbitrary inline code, CSS URLs,
    # QA controls, root mocks and private markers from an untrusted input tree.
    modules = {name for name in contents if name.endswith((".js", ".mjs"))}
    reached, pending = set(), ["preview_public_v2.js"]
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        c.require(name in modules, "public_import_missing")
        reached.add(name)
        text = contents[name].decode("utf-8")
        c.require(not re.search(r"\bimport\s*\(", text), "dynamic_import_rejected")
        for match in STATIC_IMPORT_PATTERN.finditer(text):
            target = match.group(1) or match.group(2)
            c.require(target.startswith("./") and target[2:] in modules, "public_import_invalid")
            pending.append(target[2:])
    c.require(reached == modules, "public_import_graph_incomplete")


def validate_artifact(root, *, contact_url, **inputs):
    result = validate_release(root, full_site=True, contact_url=contact_url, **inputs)
    return {**result, "siteComplete": True, "assetCount": len(c.SITE_ASSETS), "deploymentPerformed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    for name in ("candidate", "source", "approval"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-candidate-digest", required=True)
    parser.add_argument("--expected-source-fingerprint", required=True)
    parser.add_argument("--contact-url", required=True)
    args = parser.parse_args()
    try:
        result = validate_artifact(args.artifact, candidate=args.candidate, source=args.source, approval=args.approval,
            expected_candidate_digest=args.expected_candidate_digest, expected_source_fingerprint=args.expected_source_fingerprint,
            contact_url=args.contact_url)
        print(c.canonical(result).decode())
        return 0
    except (ValueError, OSError, KeyError, TypeError, c.v2.V2Error, c.qa.QAError, subprocess.SubprocessError):
        print("v2 full-site validation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
