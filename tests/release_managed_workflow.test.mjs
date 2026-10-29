import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const workflowPath = path.join(root, '.github/workflows/synthetic-public-ci.yml');
const workflow = await readFile(workflowPath, 'utf8');

function section(start, end) {
  const from = workflow.indexOf(start);
  assert.notEqual(from, -1, `missing workflow section: ${start}`);
  const to = end ? workflow.indexOf(end, from + start.length) : workflow.length;
  assert.notEqual(to, -1, `missing workflow section end: ${end}`);
  return workflow.slice(from, to);
}

test('workflow remains manual-only and staging publish is opt-in with a separate legacy migration flag', () => {
  assert.match(workflow, /^name: Synthetic public site CI$/m);
  assert.match(workflow, /^on:\n  workflow_dispatch:/m);
  assert.match(workflow, /publish_staging:[\s\S]*?type: boolean[\s\S]*?default: false/);
  assert.match(workflow, /allow_initial_legacy_migration:[\s\S]*?type: boolean[\s\S]*?default: false/);
  assert.match(workflow, /service_date:[\s\S]*?required: false[\s\S]*?type: string/);
  assert.match(workflow, /expected_previous_release_id:[\s\S]*?required: false[\s\S]*?type: string/);
  assert.match(workflow, /manifest is HTTP 404 or its HTML exactly matches root index\.html/);
  assert.doesNotMatch(workflow, /^  schedule:/m);
  assert.match(workflow, /group: dotchi-ikebukuro-staging-publish\n  cancel-in-progress: false/);
});

test('build validates optional date and expected A before fixture generation, then rejects B equal to A', () => {
  const build = section('  build:', '  validate:');
  const validation = build.indexOf('Validate build inputs and resolve service-date anchor');
  const generation = build.indexOf('Generate synthetic fixtures');
  const releaseBuild = build.indexOf('Build release-managed public site');
  const compare = build.indexOf('Compare built release with expected A');
  assert.ok(validation >= 0 && generation > validation && releaseBuild > generation && compare > releaseBuild);
  assert.match(build, /validate_release_build_inputs\.py/);
  assert.match(build, /--service-date "\$\{\{ steps\.build_inputs\.outputs\.service_date_anchor \}\}"/);
  assert.match(build, /--built-release-id "\$release_id"/);
  assert.match(build, /release_id: \$\{\{ steps\.compare_release\.outputs\.release_id \}\}/);
  assert.match(build, /service_date_anchor: \$\{\{ steps\.build_inputs\.outputs\.service_date_anchor \}\}/);
});

test('release job is main-only, depends on both validation jobs, and waits on pages-staging Environment', () => {
  const release = section('  release-and-deploy:', null);
  assert.match(release, /needs:\n      - main-branch-guard\n      - build\n      - validate/);
  assert.match(release, /if: github\.ref == 'refs\/heads\/main' && inputs\.publish_staging == true/);
  assert.match(release, /environment:\n      name: pages-staging/);
  assert.doesNotMatch(section('  build:', '  validate:'), /environment:|secrets\./);
  assert.doesNotMatch(section('  validate:', '  release-and-deploy:'), /environment:|secrets\./);
});

test('artifact sequence is release-managed build, independent validation, fetch, assembly, final validation, preflight, upload', () => {
  const build = section('  build:', '  validate:');
  const validate = section('  validate:', '  release-and-deploy:');
  const release = section('  release-and-deploy:', null);
  assert.match(build, /build_public_site\.py[\s\S]*?--release-managed/);
  assert.match(validate, /validate_public_artifact\.py --release-managed/);
  const ordered = [
    'Download validated artifact by immutable ID',
    'Fetch and validate current Production alias snapshot',
    'Assemble previous generations with new release',
    'Independently validate complete assembled artifact',
    'Recheck Production alias fingerprint immediately before upload',
    'Direct Upload assembled artifact to Cloudflare Pages staging',
  ].map((label) => release.indexOf(label));
  assert.ok(ordered.every((index) => index >= 0));
  assert.deepEqual(ordered, [...ordered].sort((a, b) => a - b));
  assert.match(release, /--base-url "\$STAGING_ALIAS"/);
  assert.match(release, /--allow-initial-legacy-migration/);
  assert.match(release, /--new-release "\$new_release_dir"/);
  assert.match(release, /--previous "\$previous_site_dir"/);
  assert.match(release, /--expected-sha256 "\$EXPECTED_FINGERPRINT"/);
  assert.match(release, /pages deploy[\s\S]*?dotchi-assembled-site-/);
  assert.ok(release.indexOf('Fetch and validate current Production alias snapshot')
    < release.indexOf('Assemble previous generations with new release'));
  assert.match(release, /test "\$snapshot_release_id" = "\$EXPECTED_PREVIOUS_RELEASE_ID"/);
  assert.ok(release.indexOf('test "$snapshot_release_id" = "$EXPECTED_PREVIOUS_RELEASE_ID"')
    < release.indexOf('Assemble previous generations with new release'));
  assert.match(release, /Record approved release preflight summary/);
  assert.ok(release.indexOf('Recheck Production alias fingerprint immediately before upload')
    < release.indexOf('Record approved release preflight summary'));
  assert.ok(release.indexOf('Record approved release preflight summary')
    < release.indexOf('Direct Upload assembled artifact to Cloudflare Pages staging'));
});

test('build-only validation records the fixed date, A/B result, and validator before Environment approval', () => {
  const validate = section('  validate:', '  release-and-deploy:');
  const release = section('  release-and-deploy:', null);
  assert.match(validate, /validate_public_artifact\.py --release-managed/);
  assert.match(validate, /Record B prevalidation summary/);
  assert.match(validate, /independent validator: \*\*PASS\*\* \(18 files \/ 8 stations\)/);
  assert.ok(validate.indexOf('Validate downloaded release-managed artifact')
    < validate.indexOf('Record B prevalidation summary'));
  assert.ok(workflow.indexOf('Record B prevalidation summary')
    < workflow.indexOf('  release-and-deploy:'));
  assert.doesNotMatch(section('  build:', '  validate:'), /secrets\.|fetch_production_artifact\.py/);
  assert.doesNotMatch(validate, /secrets\.|fetch_production_artifact\.py/);
});

test('Access and Cloudflare credentials are step-scoped and deploy targets only the existing staging project', () => {
  const release = section('  release-and-deploy:', null);
  const accessRefs = release.match(/secrets\.CF_ACCESS_CLIENT_(?:ID|SECRET)/g) ?? [];
  assert.equal(accessRefs.length, 4, 'Access values should appear only on fetch and preflight steps');
  assert.match(release, /STAGING_ALIAS: https:\/\/dotchi-ikebukuro-staging\.pages\.dev/);
  assert.match(release, /--expected-project dotchi-ikebukuro-staging/);
  assert.match(release, /--project-name=dotchi-ikebukuro-staging/);
  assert.match(release, /CLOUDFLARE_API_TOKEN: \$\{\{ secrets\.CLOUDFLARE_API_TOKEN \}\}/);
  assert.match(release, /CLOUDFLARE_ACCOUNT_ID: \$\{\{ vars\.CLOUDFLARE_ACCOUNT_ID \}\}/);
  assert.doesNotMatch(release, /set -x/);
  assert.doesNotMatch(release, /echo .*\$\{?CF_ACCESS_CLIENT_(?:ID|SECRET)|echo .*\$\{?CLOUDFLARE_API_TOKEN/);
});
