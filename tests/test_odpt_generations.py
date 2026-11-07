from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import copy
import tempfile
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import odpt_release_contract as c
import odpt_generation_contract as g
import assemble_odpt_generations as builder
from validate_odpt_generations import validate_transition
from odpt_generation_fixture import make_site, initial, change, DAY1, DAY2, DAY3
from test_odpt_public_release import inventory


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='odpt-generations-',dir='/private/tmp');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.a=make_site('A');self.addCleanup(self.a.doCleanups)
        self.b=make_site('B',now=DAY2);self.addCleanup(self.b.doCleanups)
        self.empty=self.root/'empty';self.empty.mkdir()
        self.ra,self.ia=initial(self.a,self.empty,self.root/'A')

    def updated(self):
        return change(self.root/'A',self.root/'B',fixture=self.b)

    def manifest(self,name):
        return c.load_json((self.root/name/'manifest.json').read_bytes())

    def test_initial_update_and_30_day_finite_retention(self):
        before=inventory(self.root/'A'), inventory(self.a.candidate), inventory(self.a.source)
        rb,inputs=self.updated()
        self.assertEqual(len(rb['retainedReleaseIds']),1)
        m=self.manifest('B'); old=m['retainedReleases'][0]
        self.assertEqual(old['releaseId'],self.ra['releaseId'])
        self.assertEqual(old['retainUntil'],'2026-12-10T15:00:00Z')
        self.assertGreater(c.timestamp(old['retainUntil'])-DAY2,timedelta(days=14))
        self.assertLessEqual(c.timestamp(old['retainUntil'])-DAY2,timedelta(days=32))
        self.assertEqual(rb['files'],41)
        self.assertEqual(validate_transition(self.root/'B',**inputs)['artifactDigest'],rb['artifactDigest'])
        self.assertEqual(before,(inventory(self.root/'A'),inventory(self.a.candidate),inventory(self.a.source)))
        self.assertFalse(c.load_json((self.a.candidate/'private-generator-manifest.json').read_bytes())['publicationApproved'])

    def test_empty_initial_and_legacy_are_distinguished(self):
        for contents in ('legacy html','{}'):
            path=self.empty/('index.html' if contents.startswith('legacy') else 'manifest.json');path.write_text(contents)
            args={**self.ia,'expected_previous_digest':g.read_tree(self.empty)['digest']}
            with self.assertRaisesRegex(c.ContractError,'initial_requires_explicit_empty_snapshot'):
                builder.assemble(output=self.root/'bad',**args)
            with self.assertRaises(c.ContractError):
                builder.assemble(output=self.root/'bad',**{**args,'operation':'update',
                    'expected_previous_release_id':self.ra['releaseId']})  # Never infer a legacy migration.
            path.unlink()
        missing={**self.ia,'previous':self.root/'absent'}
        with self.assertRaises(c.ContractError):builder.assemble(output=self.root/'bad',**missing)
        with self.assertRaises(c.ContractError):
            builder.assemble(output=self.root/'bad',**{**self.ia,'expected_previous_release_id':self.ra['releaseId']})

    def test_previous_id_digest_and_changed_state_refuse_update(self):
        rb,args=self.updated()
        for changes in ({'expected_previous_digest':'0'*64},{'expected_previous_release_id':'r1-'+'0'*64}):
            with self.assertRaises(c.ContractError):
                builder.assemble(output=self.root/'bad',**{**args,**changes})
        p=self.root/'A'/'styles.css';p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(c.ContractError,'previous_artifact_changed'):
            builder.assemble(output=self.root/'bad',**args)

    def test_change_after_validation_is_caught_before_output_commit(self):
        args=dict(previous=self.root/'A',expected_previous_digest=self.ra['artifactDigest'],
            expected_previous_release_id=self.ra['releaseId'],operation='update',new_release=self.b.site,
            validation_inputs=self.b.context,now=DAY2)
        original=builder.validate_transition
        for path,code in [(self.root/'A'/'styles.css','previous_artifact_changed'),
                          (self.b.site/'styles.css','new_release_changed')]:
            saved=path.read_bytes()
            def change_after(*a,**kw):
                result=original(*a,**kw)
                path.write_bytes(path.read_bytes()+b' ')
                return result
            try:
                with patch.object(builder,'validate_transition',change_after):
                    with self.assertRaisesRegex(c.ContractError,code):
                        builder.assemble(output=self.root/'bad',**args)
                self.assertFalse((self.root/'bad').exists())
            finally:path.write_bytes(saved)

    def test_rollback_restores_old_assets_metadata_and_keeps_outgoing(self):
        rb,_=self.updated()
        rr,args=change(self.root/'B',self.root/'rollback',target=self.ra['releaseId'],now=DAY3)
        m=self.manifest('rollback')
        self.assertEqual(rr['releaseId'],self.ra['releaseId'])
        self.assertEqual(rr['retainedReleaseIds'],[rb['releaseId']])
        self.assertEqual(m['metadata'],self.manifest('A')['metadata'])
        for name in c.SITE_ASSETS:
            self.assertEqual((self.root/'rollback'/name).read_bytes(),(self.root/'A'/name).read_bytes())
        self.assertEqual(validate_transition(self.root/'rollback',**args)['artifactDigest'],rr['artifactDigest'])

    def test_unknown_expired_or_unverified_rollback_refused(self):
        rb,_=self.updated()
        for rid,now in [('r1-'+'0'*64,DAY3),(rb['releaseId'],DAY3),
                        (self.ra['releaseId'],datetime(2026,12,8,15,tzinfo=timezone.utc))]:
            with self.assertRaises(c.ContractError):
                change(self.root/'B',self.root/'bad',target=rid,now=now)
        p=self.root/'B'/'releases'/self.ra['releaseId']/'assets'/'styles.css';p.unlink()
        with self.assertRaises(c.ContractError):
            change(self.root/'B',self.root/'bad',target=self.ra['releaseId'],now=DAY3)

    def test_old_toolchain_is_restored_without_using_current_source_assets(self):
        a=make_site('older',old_toolchain=True);self.addCleanup(a.doCleanups)
        ra,_=initial(a,self.empty,self.root/'old')
        rb,_=change(self.root/'old',self.root/'new',fixture=self.b)
        rr,args=change(self.root/'new',self.root/'restored',target=ra['releaseId'],now=DAY3)
        self.assertEqual(rr['releaseId'],ra['releaseId'])
        self.assertEqual(self.manifest('restored')['metadata']['codeCommit'],'a'*40)
        self.assertNotEqual((self.root/'old'/'odpt_public_runtime.mjs').read_bytes(),(self.b.site/'odpt_public_runtime.mjs').read_bytes())
        self.assertEqual((self.root/'old'/'odpt_public_runtime.mjs').read_bytes(),(self.root/'restored'/'odpt_public_runtime.mjs').read_bytes())

    def test_no_silent_prune_and_exact_delete_safety_boundary(self):
        self.updated()
        boundary=datetime(2026,12,11,15,tzinfo=timezone.utc)
        newer=make_site('C',start='2026-12-11',end='2027-01-10',now=boundary);self.addCleanup(newer.doCleanups)
        keep,_=change(self.root/'B',self.root/'keep',fixture=newer,now=boundary)
        self.assertEqual(len(keep['retainedReleaseIds']),2)
        with self.assertRaisesRegex(c.ContractError,'prune_before_deadline'):
            change(self.root/'B',self.root/'bad',fixture=newer,now=boundary-timedelta(seconds=1),prune=[self.ra['releaseId']])
        dropped,args=change(self.root/'B',self.root/'pruned',fixture=newer,now=boundary,prune=[self.ra['releaseId']])
        self.assertEqual(dropped['prunedReleaseIds'],[self.ra['releaseId']])
        self.assertEqual(len(dropped['retainedReleaseIds']),1)
        validate_transition(self.root/'pruned',**args)

    def test_retained_tamper_mixed_generation_and_unrequested_deletion_rejected(self):
        rb,args=self.updated(); root=self.root/'B'
        path=root/'releases'/self.ra['releaseId']/c.STATION_FILES['Hikawadai']
        original=path.read_bytes();path.write_bytes((self.root/'A'/'manifest.json').read_bytes())
        with self.assertRaises(c.ContractError):validate_transition(root,**args)
        path.write_bytes(original)
        m=self.manifest('B');m['retainedReleases'][0]['retainUntil']='2027-01-01T00:00:00Z'
        p=root/'manifest.json';saved=p.read_bytes();p.write_bytes(c.canonical(m))
        with self.assertRaises(c.ContractError):validate_transition(root,**args)
        p.write_bytes(saved);path.unlink()
        with self.assertRaises(c.ContractError):validate_transition(root,**args)

    def test_bounds_and_output_overwrite(self):
        args=dict(previous=self.root/'A',expected_previous_digest=self.ra['artifactDigest'],
            expected_previous_release_id=self.ra['releaseId'],operation='update',new_release=self.b.site,
            validation_inputs=self.b.context,now=DAY2)
        cap=max(g.read_tree(self.root/'A')['bytes'],g.read_tree(self.b.site)['bytes'])+1
        with patch.object(c,'MAX_TOTAL_BYTES',cap):
            with self.assertRaises(c.ContractError):builder.assemble(output=self.root/'bad',**args)
        self.updated()
        with self.assertRaises(c.ContractError):builder.assemble(output=self.root/'B',**args)
        huge=self.root/'huge';huge.mkdir();p=huge/'file'
        p.write_bytes(b'x'*(25*1024*1024))
        self.assertEqual(g.read_tree(huge)['bytes'],25*1024*1024)
        with p.open('ab') as f:f.write(b'x')
        with self.assertRaises(c.ContractError):g.read_tree(huge)

    def test_real_clock_path_revalidates_without_reinventing_assembly_time(self):
        now=datetime.now(timezone.utc)
        jst=timezone(timedelta(hours=9));start=now.astimezone(jst).date()-timedelta(days=1)
        live=make_site('real-clock-synthetic',start=start.isoformat(),end=(start+timedelta(days=30)).isoformat(),now=now)
        self.addCleanup(live.doCleanups)
        args=dict(previous=self.empty,expected_previous_digest=g.read_tree(self.empty)['digest'],operation='initial',
                  new_release=live.site,validation_inputs=live.context)
        result=builder.assemble(output=self.root/'clock-site',**args)
        self.assertEqual(validate_transition(self.root/'clock-site',**args)['artifactDigest'],result['artifactDigest'])
        self.assertTrue(result['deploymentPreflightRequired'])

    def test_stale_assembly_requires_rebuild(self):
        rb,args=self.updated()
        with self.assertRaisesRegex(c.ContractError,'assembly_stale_rebuild_required'):
            validate_transition(self.root/'B',**{**args,'now':DAY2+timedelta(days=1,seconds=1)})


if __name__=='__main__':unittest.main()
