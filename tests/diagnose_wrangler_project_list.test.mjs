import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { diagnoseProjectList } from '../scripts/diagnose_wrangler_project_list.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const script = path.join(root, 'scripts', 'diagnose_wrangler_project_list.mjs');

test('accepts valid JSON when the exact expected Pages project is present', () => {
  const result = diagnoseProjectList({
    exitCode: 0,
    stdout: JSON.stringify([{ name: 'another-project' }, { name: 'dotchi-ikebukuro-staging' }]),
    stderr: '',
    expectedProject: 'dotchi-ikebukuro-staging',
  });

  assert.deepEqual(result, { result: 'project_found', category: 'none', exitCode: 0 });
});

test('distinguishes malformed JSON, an unexpected JSON shape, and a missing project', () => {
  const common = { exitCode: 0, stderr: '', expectedProject: 'dotchi-ikebukuro-staging' };
  assert.equal(diagnoseProjectList({ ...common, stdout: '{not-json' }).result, 'json_parse_failed');
  assert.equal(diagnoseProjectList({ ...common, stdout: '{"projects":[]}' }).result, 'json_shape_invalid');
  assert.deepEqual(diagnoseProjectList({ ...common, stdout: '[{"name":"other"}]' }), {
    result: 'project_not_found', category: 'none', exitCode: 1,
  });
});

test('classifies authentication, permission, account, rate-limit, network, API, and unknown errors', () => {
  const cases = [
    ['Authentication error [code: 10000]', 'authentication', [10000]],
    ['Forbidden: missing permission', 'permission', []],
    ['Could not determine account ID', 'account', []],
    ['HTTP status 429: too many requests', 'rate_limit', []],
    ['Fetch failed: ECONNRESET', 'network', []],
    ['Cloudflare API request failed with HTTP 502', 'api_error', []],
    ['opaque failure text', 'unknown', []],
  ];

  for (const [stderr, category, cloudflareErrorCodes] of cases) {
    assert.deepEqual(diagnoseProjectList({
      exitCode: 1,
      stdout: '',
      stderr,
      expectedProject: 'dotchi-ikebukuro-staging',
    }), {
      result: 'wrangler_command_failed', category, exitCode: 1, cloudflareErrorCodes,
    });
  }
});

test('extracts only numeric Cloudflare API error codes from structured errors', () => {
  const secret = 'MOCK_SECRET_DO_NOT_PRINT_abc123';
  const stdout = JSON.stringify({
    success: false,
    errors: [{ code: 9109, message: `Authentication error: ${secret}` }],
    account: 'MOCK_ACCOUNT_ID_DO_NOT_PRINT',
  });
  const result = diagnoseProjectList({
    exitCode: 1,
    stdout,
    stderr: '',
    expectedProject: 'dotchi-ikebukuro-staging',
  });

  assert.deepEqual(result, {
    result: 'wrangler_command_failed', category: 'authentication', exitCode: 1, cloudflareErrorCodes: [9109],
  });
  assert.doesNotMatch(JSON.stringify(result), /MOCK_SECRET|MOCK_ACCOUNT_ID|authentication failed/);
});

test('CLI summary never prints captured secrets or raw Wrangler output', async () => {
  const temporaryDirectory = await mkdtemp(path.join(os.tmpdir(), 'wrangler-diagnostic-test-'));
  try {
    const secret = 'MOCK_SECRET_DO_NOT_PRINT_abc123';
    const accountId = 'MOCK_ACCOUNT_ID_DO_NOT_PRINT_987654';
    const stdoutPath = path.join(temporaryDirectory, 'stdout.txt');
    const stderrPath = path.join(temporaryDirectory, 'stderr.txt');
    await writeFile(stdoutPath, JSON.stringify({
      success: false,
      errors: [{ code: 10000, message: `Authentication error: ${secret}` }],
      account_id: accountId,
    }));
    await writeFile(stderrPath, `Authentication error [code: 10000] ${secret} ${accountId}\n`);

    const child = spawnSync(process.execPath, [
      script,
      '--exit-code', '1',
      '--stdout-file', stdoutPath,
      '--stderr-file', stderrPath,
      '--expected-project', 'dotchi-ikebukuro-staging',
    ], { encoding: 'utf8' });

    assert.equal(child.status, 1);
    assert.equal(child.stderr, '');
    assert.doesNotMatch(child.stdout, /MOCK_SECRET|MOCK_ACCOUNT_ID|Authentication error/);
    const summary = JSON.parse(child.stdout);
    assert.deepEqual(summary, {
      step: 'wrangler_pages_project_list',
      result: 'wrangler_command_failed',
      category: 'authentication',
      exit_code: 1,
      cloudflare_error_codes: [10000],
    });

    const originalStdout = await readFile(stdoutPath, 'utf8');
    assert.match(originalStdout, new RegExp(secret));
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true });
  }
});

test('unreadable or oversized diagnostic captures fail with a generic summary', async () => {
  const child = spawnSync(process.execPath, [
    script,
    '--exit-code', '0',
    '--stdout-file', path.join(os.tmpdir(), 'wrangler-diagnostic-file-that-does-not-exist'),
    '--stderr-file', path.join(os.tmpdir(), 'wrangler-diagnostic-file-that-does-not-exist-either'),
    '--expected-project', 'dotchi-ikebukuro-staging',
  ], { encoding: 'utf8' });

  assert.equal(child.status, 1);
  assert.equal(child.stderr, '');
  assert.equal(child.stdout, '{"result":"diagnostic_input_unreadable","category":"unknown","exit_code":1,"wrangler_exit_code":0}\n');
});

test('oversized capture content is not printed', async () => {
  const temporaryDirectory = await mkdtemp(path.join(os.tmpdir(), 'wrangler-diagnostic-large-test-'));
  try {
    const secret = 'MOCK_SECRET_DO_NOT_PRINT_abc123';
    const stdoutPath = path.join(temporaryDirectory, 'stdout.txt');
    const stderrPath = path.join(temporaryDirectory, 'stderr.txt');
    await writeFile(stdoutPath, `${secret}${'x'.repeat(2 * 1024 * 1024)}`);
    await writeFile(stderrPath, '');

    const child = spawnSync(process.execPath, [
      script,
      '--exit-code', '1',
      '--stdout-file', stdoutPath,
      '--stderr-file', stderrPath,
      '--expected-project', 'dotchi-ikebukuro-staging',
    ], { encoding: 'utf8' });

    assert.equal(child.status, 1);
    assert.equal(child.stderr, '');
    assert.equal(child.stdout, '{"result":"diagnostic_input_unreadable","category":"unknown","exit_code":1,"wrangler_exit_code":1}\n');
    assert.doesNotMatch(child.stdout, /MOCK_SECRET/);
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true });
  }
});
