import { expect, test, vi } from 'vitest';
import { registerSessionReset, resetUserSessionResources } from './session-reset.ts';

test('runs registered session resets until they unsubscribe', () => {
  const first = vi.fn();
  const second = vi.fn();
  const unregisterFirst = registerSessionReset(first);
  const unregisterSecond = registerSessionReset(second);

  resetUserSessionResources();
  unregisterFirst();
  resetUserSessionResources();
  unregisterSecond();

  expect(first).toHaveBeenCalledTimes(1);
  expect(second).toHaveBeenCalledTimes(2);
});
