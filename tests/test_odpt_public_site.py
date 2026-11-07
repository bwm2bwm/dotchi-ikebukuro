"""Full-site tests use explicit synthetic inputs and approvals only."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_odpt_public_release as data_tests
import odpt_release_contract as c
from assemble_odpt_public_site import assemble
from validate_odpt_public_site import validate_artifact
from validate_odpt_public_release import validate_artifact as validate_data
from assemble_public_release import retention_deadline, AssemblyError
from validate_public_artifact import validate_release_managed_artifact, ArtifactValidationError

NOW, inventory = data_tests.NOW, data_tests.inventory


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.f = data_tests.ReleaseTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.build()
        self.output = self.f.root / 'site'
        self.args = dict(candidate=self.f.candidate, source=self.f.source, approval=self.f.approval,
            expected_candidate_digest=self.f.request['candidateDigest'], expected_source_fingerprint=self.f.fp, now=NOW)
        self.contact = 'https://example.invalid/contact?kind=synthetic&lang=ja'

    def build(self, output=None, contact=None):
        return assemble(data_release=self.f.output, output=output or self.output,
                        contact_url=self.contact if contact is None else contact, **self.args)

    def validate(self):
        return validate_artifact(self.output, contact_url=self.contact, **self.args)

    def manifest(self):
        return c.load_json((self.output / 'manifest.json').read_bytes())

    def write_manifest(self, m):
        (self.output / 'manifest.json').write_bytes(c.canonical(m))

    def reseal(self, m):
        """Recompute hashes as a hostile artifact author, not a trusted builder."""
        old_id = m['releaseId']
        for r in m['releaseDescriptor']['assets']:
            raw = (self.output / r['path']).read_bytes()
            r.update(bytes=len(raw), sha256=c.digest(raw))
        new_id = c.release_id(m['releaseDescriptor'])
        old_dir = self.output / 'releases' / old_id
        new_dir = old_dir.with_name(new_id)
        if new_dir != old_dir:
            old_dir.rename(new_dir)
        m['releaseId'] = new_id
        for station, name in c.STATION_FILES.items():
            path = new_dir / name
            env = c.load_json(path.read_bytes()); env['releaseId'] = new_id
            raw = c.canonical(env); path.write_bytes(raw)
            m['stations'][station] = dict(url=f'/releases/{new_id}/{name}', bytes=len(raw), sha256=c.digest(raw))
        self.write_manifest(m)

    def test_full_site_and_input_immutability_determinism(self):
        before = inventory(self.f.root)
        result = self.build()
        self.assertTrue(result['siteComplete'])
        self.assertFalse(result['deploymentPerformed'])
        self.assertEqual(result['assetCount'], 12)
        self.assertEqual(len([p for p in self.output.rglob('*') if p.is_file()]), 21)
        self.assertEqual(self.validate()['releaseId'], result['releaseId'])
        old = c.load_json((self.f.output/'manifest.json').read_bytes())
        new = self.manifest()
        self.assertNotEqual(new['releaseId'], old['releaseId'])
        self.assertEqual(new['metadata'], old['metadata'])
        self.assertEqual(new['retainedReleases'], [])
        for name, original in before.items():
            self.assertEqual(inventory(self.f.root)[name], original)
        other = self.f.root/'same-site'; self.build(output=other)
        self.assertEqual({k:v[:2] for k,v in inventory(self.output).items()}, {k:v[:2] for k,v in inventory(other).items()})
        with self.assertRaises(c.ContractError):
            validate_data(self.output, **self.args)
        with self.assertRaises(c.ContractError):
            validate_data(self.output, full_site=True, **self.args)  # Cannot bypass contact/asset validation.
        with self.assertRaises(ArtifactValidationError):
            validate_release_managed_artifact(self.output)

    def test_each_asset_tamper_and_missing_are_rejected(self):
        self.build()
        for name in c.SITE_ASSETS:
            path = self.output/name; raw = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(raw+b' ')
                with self.assertRaises(c.ContractError): self.validate()
                path.unlink()
                with self.assertRaises(c.ContractError): self.validate()
                path.write_bytes(raw)

    def test_recomputed_mixed_asset_still_rejected_by_trusted_toolchain(self):
        self.build()
        path = self.output/'preview_public_v2.js'; path.write_bytes(path.read_bytes()+b'\n// other generation\n')
        self.reseal(self.manifest())
        with self.assertRaisesRegex(c.ContractError, 'site_toolchain_asset_mismatch'):
            self.validate()

    def test_contact_is_explicit_bound_and_cannot_be_substituted(self):
        self.build()
        with self.assertRaisesRegex(c.ContractError, 'contact_input_mismatch'):
            validate_artifact(self.output, contact_url='https://example.invalid/other', **self.args)
        original = self.manifest()['releaseId']
        other = self.f.root/'other-site'; self.build(output=other, contact='https://example.invalid/other')
        self.assertNotEqual(original, c.load_json((other/'manifest.json').read_bytes())['releaseId'])
        (self.output/'index.html').write_bytes((other/'index.html').read_bytes())
        self.reseal(self.manifest())
        with self.assertRaisesRegex(c.ContractError, 'contact_input_mismatch'): self.validate()

    def test_unsafe_or_missing_contact_no_output_and_existing_output_refused(self):
        for contact in ('', 'javascript:alert(1)', 'http://example.invalid/', 'https://u:p@example.invalid/', 'https://example.invalid/\n'):
            with self.subTest(contact=contact), self.assertRaises(c.ContractError):
                self.build(contact=contact)
            self.assertFalse(self.output.exists())
        self.build(); before=inventory(self.output)
        with self.assertRaises(c.ContractError): self.build()
        self.assertEqual(before, inventory(self.output))

    def test_unknown_schema_kind_descriptor_asset_path_and_metadata_rejected(self):
        self.build(); original=self.manifest()
        changes=[lambda m:m.update(schemaVersion=3), lambda m:m.update(artifactKind=c.KIND),
            lambda m:m['releaseDescriptor']['assets'].pop(),
            lambda m:m['releaseDescriptor']['assets'][0].update(path='../index.html'),
            lambda m:m['metadata']['quality']['resolution']['classes'].update(C=1)]
        for change in changes:
            m=copy.deepcopy(original); change(m); self.write_manifest(m)
            with self.assertRaises((c.ContractError,c.v2.V2Error)): self.validate()

    def test_station_from_data_generation_is_rejected_even_with_matching_raw_hash(self):
        self.build(); m=self.manifest()
        original=c.load_json((self.f.output/'manifest.json').read_bytes())
        station='Hikawadai'
        raw=(self.f.output/original['stations'][station]['url'].lstrip('/')).read_bytes()
        (self.output/m['stations'][station]['url'].lstrip('/')).write_bytes(raw)
        m['stations'][station].update(bytes=len(raw),sha256=c.digest(raw)); self.write_manifest(m)
        with self.assertRaisesRegex(c.ContractError,'envelope_profile_mismatch'): self.validate()

    def test_extra_qa_symlink_and_retained_generation_fail_closed(self):
        self.build()
        extra=self.output/'preview_odpt_v2_qa.mjs'; extra.write_text('QA controls')
        with self.assertRaises(c.ContractError): self.validate()
        extra.unlink()
        asset=self.output/'odpt_public.css'; raw=asset.read_bytes(); asset.unlink(); asset.symlink_to(c.SITE_ASSETS['odpt_public.css'])
        with self.assertRaises(c.ContractError): self.validate()
        asset.unlink(); asset.write_bytes(raw)
        m=self.manifest(); m['retainedReleases']=[{'releaseId':'r1-'+'0'*64}]; self.write_manifest(m)
        with self.assertRaises(c.ContractError): self.validate()

    def test_existing_retention_policy_unchanged_for_long_validity(self):
        retired=datetime(2026,11,10,tzinfo=timezone.utc)
        with self.assertRaises(AssemblyError):
            retention_deadline(retired,datetime(2026,12,9,tzinfo=timezone.utc))


if __name__ == '__main__':
    unittest.main()
