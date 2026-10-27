import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ERROR_CATEGORIES = Object.freeze([
  'authentication',
  'permission',
  'account',
  'rate_limit',
  'network',
  'api_error',
  'unknown',
]);

const MAX_CAPTURE_BYTES = 2 * 1024 * 1024;

function isSafeCode(value) {
  return Number.isInteger(value) && value >= 0 && value <= 999999;
}

function parseJsonEnvelope(text) {
  const candidates = [text.trim()];
  const firstBrace = text.indexOf('{');
  const lastBrace = text.lastIndexOf('}');
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    candidates.push(text.slice(firstBrace, lastBrace + 1));
  }

  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch {
      // Try the next bounded candidate; raw content is never sent to logs.
    }
  }
  return null;
}

function extractCloudflareCodes(texts) {
  const codes = new Set();
  for (const text of texts) {
    const envelope = parseJsonEnvelope(text);
    if (envelope && typeof envelope === 'object' && Array.isArray(envelope.errors)) {
      for (const error of envelope.errors) {
        if (error && typeof error === 'object' && isSafeCode(error.code)) {
          codes.add(error.code);
        }
      }
    }

    const labeledCode = /(?:\[\s*code\s*:\s*|\b(?:cloudflare\s+)?error\s+code\s*[:=]\s*)(\d{1,6})\b/gi;
    for (const match of text.matchAll(labeledCode)) {
      const code = Number(match[1]);
      if (isSafeCode(code)) codes.add(code);
    }
  }
  return [...codes].sort((a, b) => a - b).slice(0, 5);
}

function classifyFailure(text) {
  const normalized = text.toLowerCase();
  const rules = [
    ['authentication', /authentication error|unauthori[sz]ed|invalid (?:cloudflare )?(?:api )?token|token (?:is )?(?:invalid|expired)|expired api token/],
    ['permission', /forbidden|permission denied|missing permission|insufficient permissions|not authorized|access denied/],
    ['account', /could not determine (?:the )?account|invalid account|account(?: id)?[^\n]{0,60}(?:not found|invalid|missing)/],
    ['rate_limit', /rate[ -]?limit|too many requests|http(?: status)?[^\n]{0,20}\b429\b/],
    ['network', /econn(?:refused|reset|aborted)|enotfound|etimedout|fetch failed|network error|tls error|socket hang up/],
    ['api_error', /cloudflare api|api request|api error|http(?: status)?[^\n]{0,20}\b[45]\d\d\b/],
  ];
  return rules.find(([, pattern]) => pattern.test(normalized))?.[0] ?? 'unknown';
}

export function diagnoseProjectList({ wranglerExitCode, stdout, stderr, expectedProject }) {
  if (!Number.isInteger(wranglerExitCode) || wranglerExitCode < 0 || wranglerExitCode > 255) {
    return {
      result: 'diagnostic_input_invalid',
      category: 'unknown',
      wranglerExitCode: null,
      diagnosticExitCode: 1,
    };
  }

  if (wranglerExitCode !== 0) {
    const texts = [stdout, stderr];
    return {
      result: 'wrangler_command_failed',
      category: classifyFailure(texts.join('\n')),
      wranglerExitCode,
      diagnosticExitCode: 1,
      cloudflareErrorCodes: extractCloudflareCodes(texts),
    };
  }

  let projects;
  try {
    projects = JSON.parse(stdout.replace(/^\uFEFF/, '').trim());
  } catch {
    return {
      result: 'json_parse_failed', category: 'unknown', wranglerExitCode: 0, diagnosticExitCode: 1,
    };
  }

  if (!Array.isArray(projects) || projects.some(project => (
    !project || typeof project !== 'object' || Array.isArray(project) || typeof project['Project Name'] !== 'string'
  ))) {
    return {
      result: 'json_shape_invalid', category: 'unknown', wranglerExitCode: 0, diagnosticExitCode: 1,
    };
  }

  if (!projects.some(project => project['Project Name'] === expectedProject)) {
    return { result: 'project_not_found', category: 'none', wranglerExitCode: 0, diagnosticExitCode: 1 };
  }

  return { result: 'project_found', category: 'none', wranglerExitCode: 0, diagnosticExitCode: 0 };
}

async function readCapture(filename) {
  const fileInfo = await stat(filename);
  if (fileInfo.size > MAX_CAPTURE_BYTES) {
    throw new Error('capture_too_large');
  }
  const buffer = await readFile(filename);
  if (buffer.byteLength > MAX_CAPTURE_BYTES) {
    throw new Error('capture_too_large');
  }
  return buffer.toString('utf8');
}

function parseArguments(argv) {
  const options = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith('--') || value === undefined || options.has(key)) return null;
    options.set(key, value);
  }
  const allowed = ['--wrangler-exit-code', '--stdout-file', '--stderr-file', '--expected-project'];
  if (options.size !== allowed.length || allowed.some(key => !options.has(key))) return null;
  return options;
}

export async function runDiagnostic(argv) {
  const options = parseArguments(argv);
  if (!options || !/^\d{1,3}$/.test(options.get('--wrangler-exit-code'))) {
    process.stdout.write(`${JSON.stringify({
      result: 'diagnostic_input_invalid',
      category: 'unknown',
      wrangler_exit_code: null,
      diagnostic_exit_code: 1,
    })}\n`);
    return 1;
  }

  const wranglerExitCode = Number(options.get('--wrangler-exit-code'));
  let result;
  try {
    result = diagnoseProjectList({
      wranglerExitCode,
      stdout: await readCapture(options.get('--stdout-file')),
      stderr: await readCapture(options.get('--stderr-file')),
      expectedProject: options.get('--expected-project'),
    });
  } catch {
    process.stdout.write(`${JSON.stringify({
      result: 'diagnostic_input_unreadable',
      category: 'unknown',
      wrangler_exit_code: wranglerExitCode,
      diagnostic_exit_code: 1,
    })}\n`);
    return 1;
  }

  const safeSummary = {
    step: 'wrangler_pages_project_list',
    result: result.result,
    category: ERROR_CATEGORIES.includes(result.category) || result.category === 'none' ? result.category : 'unknown',
    wrangler_exit_code: result.wranglerExitCode,
    diagnostic_exit_code: result.diagnosticExitCode,
    ...(result.cloudflareErrorCodes ? { cloudflare_error_codes: result.cloudflareErrorCodes } : {}),
  };
  process.stdout.write(`${JSON.stringify(safeSummary)}\n`);
  return result.diagnosticExitCode;
}

const scriptPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
if (scriptPath && import.meta.url === pathToFileURL(scriptPath).href) {
  const exitCode = await runDiagnostic(process.argv.slice(2));
  process.exitCode = exitCode;
}
