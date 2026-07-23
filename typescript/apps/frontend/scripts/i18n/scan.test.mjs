import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { checkUnusedKeys } from './scan.mjs';

let fixtureDir;

beforeEach(() => {
  fixtureDir = mkdtempSync(join(tmpdir(), 'nohiki-i18n-scan-'));
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
  vi.spyOn(console, 'log').mockImplementation(() => undefined);
  vi.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  rmSync(fixtureDir, { force: true, recursive: true });
  vi.restoreAllMocks();
});

function runUnusedCheck(source, messages) {
  const sourceFile = join(fixtureDir, 'fixture.tsx');
  writeFileSync(sourceFile, source);
  const getAllFiles = () => [sourceFile];
  return checkUnusedKeys({ en: { 'common.json': messages } }, getAllFiles, fixtureDir);
}

describe('checkUnusedKeys', () => {
  test('fails and reports a planted unused locale key', () => {
    const passed = runUnusedCheck("const label = t('used.key');", {
      planted: { unused: 'Unused' },
      used: { key: 'Used' },
    });

    expect(passed).toBe(false);
    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining('Found 1 unused locale key'),
    );
    expect(console.warn).toHaveBeenCalledWith(expect.stringContaining('common:planted.unused'));
  });

  test('does not report keys below a planted dynamic translation prefix', () => {
    const dynamicSource = ['const message = t(`oauth.errors.', '$', '{code}`);'].join('');
    const passed = runUnusedCheck(dynamicSource, {
      oauth: { errors: { accessDenied: 'Denied', expired: 'Expired' } },
    });

    expect(passed).toBe(true);
    expect(console.error).not.toHaveBeenCalled();
    expect(console.log).toHaveBeenCalledWith(expect.stringContaining('No unused locale keys'));
  });
});
