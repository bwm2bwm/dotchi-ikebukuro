import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { diagnoseProjectList } from '../scripts/diagnose_wrangler_project_list.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const script = path.join(root, 'scripts', 'diagnose_wrangler_project_list.mjs');
const expectedProject = 'dotchi-ikebukuro-staging';
const wranglerRows = [
  { 'Project Name': 'other-project', 'Project Domains': ['other.pages.dev'], 'Git Provider': null },
  { 'Project Name': expectedProject, 'Project Domains': [`${expectedProject}.pages.dev`], 'Git Provider': null },
];

function diagnose({ wranglerExitCode = 0, stdout = '', stderr = '' } = {}) {
  return diagnoseProjectList({ wranglerExitCode, stdout, stderr, expectedProject });
}

test('accepts Wrangler 4.152.0 display rows when the exact project is present', () => {
  assert.deepEqual(diagnose({ stdout: JSON.stringify(wranglerRows) }), {
    result: 'project_found', category: 'none', wranglerExitCode: 0, diagnosticExitCode: 0,
  });
});

test('reports an absent project as a closed failure', () => {
  assert.deepEqual(diagnose({ stdout: JSON.stringify([wranglerRows[0]]) }), {
    result: 'project_not_found', category: 'none', wranglerExitCode: 0, diagnosticExitCode: 1,
  });
});

test('distinguishes malformed JSON from an unknown JSON shape', () => {
  assert.deepEqual(diagnose({ stdout: '{not-json' }), {
    result: 'json_parse_failed', category: 'unknown', wranglerExitCode: 0, diagnosticExitCode: 1,
  });
  for (const stdout of ['{"projects":[]}', '[{"name":"dotchi-ikebukuro-staging"}]', '[null]', '[["row"]]']) {
    assert.deepEqual(diagnose({ stdout }), {
      result: 'json_shape_invalid', category: 'unknown', wranglerExitCode: 0, diagnosticExitCode: 1,
    });
  }
});

test('keeps Wrangler command failure distinct from diagnostic failure', () => {
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
    assert.deepEqual(diagnose({ wranglerExitCode: 7, stderr }), {
      result: 'wrangler_command_failed', category, wranglerExitCode: 7, diagnosticExitCode: 1, cloudflareErrorCodes,
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
  const result = diagnoseProjectList({ wranglerExitCode: 1, stdout, stderr: '', expectedProject });
  assert.deepEqual(result, {
    result: 'wrangler_command_failed', category: 'authentication', wranglerExitCode: 1,
    diagnosticExitCode: 1, cloudflareErrorCodes: [9109],
  });
  assert.doesNotMatch(JSON.stringify(result), /MOCK_SECRET|MOCK_ACCOUNT_ID|Authentication error/);
});

test('CLI summary separates both exit codes and never prints captured credentials or raw output', async () => {
  const temporaryDirectory = await mkdtemp(path.join(os.tmpdir(), 'wrangler-diagnostic-test-'));
  try {
    const secret = 'MOCK_SECRET_DO_NOT_PRINT_abc123';
    const accountId = 'MOCK_ACCOUNT_ID_DO_NOT_PRINT_987654';
    const stdoutPath = path.join(temporaryDirectory, 'stdout.txt');
    const stderrPath = path.join(temporaryDirectory, 'stderr.txt');
    await writeFile(stdoutPath, `{"Project Name":"${secret}"}`);
    await writeFile(stderrPath, `Authentication error [code: 10000] ${secret} ${accountId}\n`);

    const child = spawnSync(process.execPath, [
      script,
      '--wrangler-exit-code', '1',
      '--stdout-file', stdoutPath,
      '--stderr-file', stderrPath,
      '--expected-project', expectedProject,
    ], { encoding: 'utf8' });

    assert.equal(child.status, 1);
    assert.equal(child.stderr, '');
    assert.doesNotMatch(child.stdout, /MOCK_SECRET|MOCK_ACCOUNT_ID|Authentication error/);
    assert.deepEqual(JSON.parse(child.stdout), {
      step: 'wrangler_pages_project_list',
      result: 'wrangler_command_failed',
      category: 'authentication',
      wrangler_exit_code: 1,
      diagnostic_exit_code: 1,
      cloudflare_error_codes: [10000],
    });
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true });
  }
});

test('CLI reports Wrangler success separately when JSON shape validation fails', async () => {
  const temporaryDirectory = await mkdtemp(path.join(os.tmpdir(), 'wrangler-diagnostic-shape-test-'));
  try {
    const stdoutPath = path.join(temporaryDirectory, 'stdout.txt');
    const stderrPath = path.join(temporaryDirectory, 'stderr.txt');
    await writeFile(stdoutPath, '[{"name":"dotchi-ikebukuro-staging"}]');
    await writeFile(stderrPath, '');
    const child = spawnSync(process.execPath, [
      script,
      '--wrangler-exit-code', '0',
      '--stdout-file', stdoutPath,
      '--stderr-file', stderrPath,
      '--expected-project', expectedProject,
    ], { encoding: 'utf8' });
    assert.equal(child.status, 1);
    assert.deepEqual(JSON.parse(child.stdout), {
      step: 'wrangler_pages_project_list', result: 'json_shape_invalid', category: 'unknown',
      wrangler_exit_code: 0, diagnostic_exit_code: 1,
    });
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true });
  }
});

test('unreadable captures fail with a safe summary and preserve Wrangler status', async () => {
  const child = spawnSync(process.execPath, [
    script,
    '--wrangler-exit-code', '0',
    '--stdout-file', path.join(os.tmpdir(), 'wrangler-diagnostic-file-that-does-not-exist'),
    '--stderr-file', path.join(os.tmpdir(), 'wrangler-diagnostic-file-that-does-not-exist-either'),
    '--expected-project', expectedProject,
  ], { encoding: 'utf8' });
  assert.equal(child.status, 1);
  assert.equal(child.stderr, '');
  assert.deepEqual(JSON.parse(child.stdout), {
    result: 'diagnostic_input_unreadable', category: 'unknown',
    wrangler_exit_code: 0, diagnostic_exit_code: 1,
  });
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
      '--wrangler-exit-code', '1',
      '--stdout-file', stdoutPath,
      '--stderr-file', stderrPath,
      '--expected-project', expectedProject,
    ], { encoding: 'utf8' });
    assert.equal(child.status, 1);
    assert.equal(child.stderr, '');
    assert.deepEqual(JSON.parse(child.stdout), {
      result: 'diagnostic_input_unreadable', category: 'unknown',
      wrangler_exit_code: 1, diagnostic_exit_code: 1,
    });
    assert.doesNotMatch(child.stdout, /MOCK_SECRET/);
  } finally {
    await rm(temporaryDirectory, { recursive: true, force: true });
  }
});
