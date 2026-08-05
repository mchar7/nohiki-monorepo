import { afterEach, expect, test, vi } from 'vitest';

import { checkLocaleConsistency } from './compare.mjs';

afterEach(() => {
  vi.restoreAllMocks();
});

test('fails for extra locale files and keys', () => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);

  const passed = checkLocaleConsistency({
    en: { 'common.json': { existing: 'Existing' } },
    'fr-CA': {
      'common.json': { existing: 'Existant', extra: 'Supplémentaire' },
      'extra.json': { key: 'Value' },
    },
  });

  expect(passed).toBe(false);
  expect(console.error).toHaveBeenCalledWith(
    expect.stringContaining('Extra file in fr-CA: extra.json'),
  );
  expect(console.error).toHaveBeenCalledWith(
    expect.stringContaining('fr-CA/common.json: Extra keys (not in en): extra'),
  );
});
