#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import process from 'node:process';

const artifactDir = '/artifacts/playwright';
const frontendDir = '/workspace/typescript/apps/frontend';
const config = 'e2e/playwright.k8s.config.ts';
const publicOrigin = 'http://nohiki.localhost';

function run(args, outputPath) {
  return new Promise((resolve) => {
    const child = spawn('pnpm', ['exec', 'playwright', 'test', `--config=${config}`, ...args], {
      cwd: frontendDir,
      env: {
        ...process.env,
        CI: 'true',
        E2E_BASE_URL: publicOrigin,
        E2E_ARTIFACT_DIR: artifactDir,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    child.stdout.on('data', (chunk) => {
      output += chunk;
      process.stdout.write(chunk);
    });
    child.stderr.on('data', (chunk) => {
      output += chunk;
      process.stderr.write(chunk);
    });
    child.on('close', async (code) => {
      await writeFile(outputPath, output, 'utf8');
      resolve(code ?? 1);
    });
  });
}

const outcomeByStatus = {
  passed: 'passed',
  skipped: 'skipped',
  timedOut: 'timedOut',
  interrupted: 'interrupted',
};

function createOutcomeCounts() {
  return { passed: 0, failed: 0, skipped: 0, timedOut: 0, interrupted: 0, retried: 0 };
}

function recordTestOutcome(outcomeCounts, test) {
  outcomeCounts.retried += Math.max(0, (test.results?.length ?? 0) - 1);
  const status = test.results?.at(-1)?.status;
  const outcome = outcomeByStatus[status ?? 'interrupted'] ?? 'failed';
  outcomeCounts[outcome] += 1;
}

function recordSpecOutcomes(outcomeCounts, spec) {
  for (const test of spec.tests ?? []) {
    recordTestOutcome(outcomeCounts, test);
  }
}

function recordSuiteOutcomes(outcomeCounts, suite) {
  for (const spec of suite.specs ?? []) {
    recordSpecOutcomes(outcomeCounts, spec);
  }
  for (const child of suite.suites ?? []) {
    recordSuiteOutcomes(outcomeCounts, child);
  }
}

function outcomes(reportData) {
  const outcomeCounts = createOutcomeCounts();
  for (const suite of reportData.suites ?? []) {
    recordSuiteOutcomes(outcomeCounts, suite);
  }
  return outcomeCounts;
}

async function readJsonReport(reportPath) {
  try {
    return JSON.parse(await readFile(reportPath, 'utf8'));
  } catch {
    return { suites: [] };
  }
}

async function preCleanPrimaryIdentity() {
  const login = await fetch(`${publicOrigin}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Origin: publicOrigin },
    body: JSON.stringify({ email: 'e2e-playwright@example.com', password: 'PlaywrightP@ss123!' }),
  });
  if (login.status === 401 || login.status === 404) return true;
  if (!login.ok) return false;
  const cookies = login.headers
    .getSetCookie()
    .map((value) => value.split(';', 1)[0])
    .join('; ');
  if (!cookies) return false;
  const response = await fetch(`${publicOrigin}/api/v1/account`, {
    method: 'DELETE',
    headers: { Cookie: cookies, Origin: publicOrigin },
  });
  return response.status === 204 || response.status === 404;
}

async function cleanupPrimaryIdentity() {
  const statePath = `${frontendDir}/e2e/.output/auth/primary-user.json`;
  let state;
  try {
    state = JSON.parse(await readFile(statePath, 'utf8'));
  } catch {
    return true;
  }
  const cookies = (state.cookies ?? []).map(({ name, value }) => `${name}=${value}`).join('; ');
  if (!cookies) return false;
  const response = await fetch(`${publicOrigin}/api/v1/account`, {
    method: 'DELETE',
    headers: { Cookie: cookies, Origin: publicOrigin },
  });
  return response.status === 204 || response.status === 401 || response.status === 404;
}

await mkdir(artifactDir, { recursive: true });
if (process.env.E2E_BASE_URL !== publicOrigin)
  throw new Error(`E2E_BASE_URL must be ${publicOrigin}`);
const collectionExitCode = await run(
  ['--list', '--reporter=list', '--retries=0'],
  `${artifactDir}/collection.txt`,
);
const collection = await readFile(`${artifactDir}/collection.txt`, 'utf8');
const match = collection.match(/Total:\s+(?<collected>\d+) tests? in (?<files>\d+) files?/u);
const collected = Number.parseInt(match?.groups?.collected ?? '0', 10);
const files = Number.parseInt(match?.groups?.files ?? '0', 10);
const preCleanupSucceeded = await preCleanPrimaryIdentity();
let runExitCode = 1;
let cleanupSucceeded = false;
try {
  if (collectionExitCode === 0 && collected > 0) {
    runExitCode = await run(['--retries=0'], `${artifactDir}/playwright.log`);
  }
} finally {
  cleanupSucceeded = await cleanupPrimaryIdentity();
}
const report = await readJsonReport(`${artifactDir}/results.json`);
const counts = outcomes(report);
const executed = Object.values(counts).reduce((sum, value) => sum + value, 0) - counts.retried;
const executionValid =
  collectionExitCode === 0 &&
  runExitCode === 0 &&
  collected > 0 &&
  executed === collected &&
  counts.failed === 0 &&
  counts.skipped === 0 &&
  counts.timedOut === 0 &&
  counts.interrupted === 0 &&
  counts.retried === 0;
const valid = preCleanupSucceeded && cleanupSucceeded && executionValid;
const result = {
  contract: 'nohiki-playwright-verification/v1',
  status: valid ? 'passed' : 'failed',
  collected,
  files,
  executed,
  ...counts,
  collectionExitCode,
  runExitCode,
  preCleanupSucceeded,
  cleanupSucceeded,
  failureEvidence:
    'results/**/trace.zip retains console and network events with failure screenshots/videos',
};
await writeFile(`${artifactDir}/result.json`, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
process.stdout.write(`${JSON.stringify(result)}\n`);
process.exit(valid ? 0 : 1);
