import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const workflow = await readFile(path.join(root, '.github/workflows/cloudflare-production-fetch-diagnostic.yml'), 'utf8');
const publishWorkflow = await readFile(path.join(root, '.github/workflows/synthetic-public-ci.yml'), 'utf8');

test('production fetch diagnostic is manual, main-only, read-only, and Environment gated', () => {
  assert.match(workflow, /^on:\n  workflow_dispatch:\s*$/m);
  assert.doesNotMatch(workflow, /^  schedule:/m);
  assert.match(workflow, /^permissions:\n  contents: read$/m);
  assert.match(workflow, /needs: main-branch-guard/);
  assert.match(workflow, /if: github\.ref == 'refs\/heads\/main'/);
  assert.match(workflow, /environment:\n      name: pages-staging/);
  assert.match(workflow, /CF_ACCESS_CLIENT_ID: \$\{\{ secrets\.CF_ACCESS_CLIENT_ID \}\}/);
  assert.match(workflow, /CF_ACCESS_CLIENT_SECRET: \$\{\{ secrets\.CF_ACCESS_CLIENT_SECRET \}\}/);
  assert.doesNotMatch(workflow, /CLOUDFLARE_API_TOKEN|wrangler|pages deploy|upload-artifact|actions\/upload-artifact/);
  assert.doesNotMatch(workflow, /set -x|echo .*CF_ACCESS_CLIENT/);
  assert.match(workflow, /unset CF_ACCESS_CLIENT_ID CF_ACCESS_CLIENT_SECRET/);
  assert.match(workflow, /GITHUB_STEP_SUMMARY/);
});

test('diagnostic requires release-managed and reuses the validated snapshot for a metadata-only summary', () => {
  assert.match(workflow, /fetch_args=\(fetch /);
  assert.match(workflow, /scripts\/fetch_production_artifact\.py/);
  assert.doesNotMatch(workflow, /--allow-initial-legacy-migration/);
  assert.match(workflow, /--base-url "\$PRODUCTION_ALIAS"/);
  assert.match(workflow, /CF_ACCESS_CLIENT_ID: \$\{\{ secrets\.CF_ACCESS_CLIENT_ID \}\}/);
  assert.match(workflow, /rm -rf -- "\$snapshot_parent"/);
  assert.match(workflow, /summarize_production_artifact_snapshot\.py --snapshot "\$snapshot_dir"/);
  assert.match(workflow, /manifest_classification=release-managed/);
  assert.match(workflow, /fingerprint_match=confirmed/);
  assert.match(workflow, /independent_validator=passed/);
  assert.ok(workflow.includes('HTTP\\ status\\ ([0-9]{3})\\ for\\ request_path=([A-Za-z0-9._/-]+)'));
  assert.ok(workflow.includes('/manifest.json) failure_stage=manifest_request'));
  assert.ok(workflow.includes('/) failure_stage=root_request'));
  assert.ok(workflow.includes('/index.html|/styles.css|/preview.css|/preview_public.js'));
  assert.ok(workflow.includes('failure_stage=static_asset_request'));
  assert.ok(workflow.includes('/releases/*|/timetable.json|/timetable-*.json) failure_stage=artifact_file_request'));
  assert.ok(workflow.includes('*) failure_stage=unclassified_http_request'));
  assert.match(workflow, /request_path=\$request_path/);
  assert.doesNotMatch(workflow, /index\.html\) failure_stage=spa_root_request/);
  assert.match(workflow, /failure_stage=/);
  assert.match(workflow, /http_status=/);
  assert.match(workflow, /error_type=/);
  assert.match(workflow, /manifest_classification=legacy_rejected/);
  assert.match(workflow, /printf '%s\\n' "\$summary" >> "\$GITHUB_STEP_SUMMARY"/);
  assert.doesNotMatch(workflow, /echo ["']?\$fetch_result|echo .*CF_ACCESS_CLIENT/);
  assert.doesNotMatch(publishWorkflow, /cloudflare-production-fetch-diagnostic/);
});
