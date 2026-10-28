import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const workflow = await readFile(path.join(root, '.github/workflows/cloudflare-access-diagnostic.yml'), 'utf8');
const script = await readFile(path.join(root, 'scripts/compare_access_http_clients.py'), 'utf8');
const publishWorkflow = await readFile(path.join(root, '.github/workflows/synthetic-public-ci.yml'), 'utf8');

test('diagnostic workflow is manual, main-only, read-only, and Environment gated', () => {
  assert.match(workflow, /^on:\n  workflow_dispatch:\s*$/m);
  assert.match(workflow, /if: github\.ref == 'refs\/heads\/main'/);
  assert.match(workflow, /environment:\n      name: pages-staging/);
  assert.match(workflow, /^permissions:\n  contents: read$/m);
  assert.match(workflow, /CF_ACCESS_CLIENT_ID: \$\{\{ secrets\.CF_ACCESS_CLIENT_ID \}\}/);
  assert.match(workflow, /CF_ACCESS_CLIENT_SECRET: \$\{\{ secrets\.CF_ACCESS_CLIENT_SECRET \}\}/);
  assert.doesNotMatch(workflow, /CLOUDFLARE_API_TOKEN|wrangler|pages deploy|upload-artifact/);
  assert.doesNotMatch(workflow, /set -x|echo .*CF_ACCESS_CLIENT/);
  assert.doesNotMatch(workflow, /actions\/upload-artifact/);
});

test('diagnostic runs the fixed curl/Python comparator and leaves the publishing workflow untouched', () => {
  assert.match(workflow, /scripts\/compare_access_http_clients\.py --run-live/);
  assert.match(script, /URL = "https:\/\/dotchi-ikebukuro-staging\.pages\.dev\/timetable-Wakoshi\.json"/);
  assert.match(script, /"--http1\.1"/);
  assert.match(script, /"--disable"/);
  assert.match(script, /Accept: application\/json/);
  assert.match(script, /Accept-Encoding: identity/);
  assert.match(script, /_NoRedirect/);
  assert.match(script, /CF-Access-Client-Id/);
  assert.match(script, /CF-Access-Client-Secret/);
  assert.match(script, /--config/);
  assert.match(script, /input=_curl_config/);
  assert.doesNotMatch(publishWorkflow, /compare_access_http_clients/);
  assert.doesNotMatch(workflow, /CLOUDFLARE_API_TOKEN|wrangler|pages deploy|upload-artifact/);
});
