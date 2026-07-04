import { describe, expect } from 'vitest';
import { getDashboardUserStage } from './getDashboardUserStage.ts';

describe('getDashboardUserStage', () => {
  test('returns "new" when profileCount is 0 (all zeros)', () => {
    expect(getDashboardUserStage({ profileCount: 0, correlationCount: 0, documentCount: 0 })).toBe(
      'new',
    );
  });

  test('returns "new" when profileCount is 0 even with other data', () => {
    expect(getDashboardUserStage({ profileCount: 0, correlationCount: 5, documentCount: 3 })).toBe(
      'new',
    );
  });

  test('returns "getting-started" when only profiles exist', () => {
    expect(getDashboardUserStage({ profileCount: 1, correlationCount: 0, documentCount: 0 })).toBe(
      'getting-started',
    );
  });

  test('returns "getting-started" when profiles and correlations exist but no documents', () => {
    expect(getDashboardUserStage({ profileCount: 1, correlationCount: 5, documentCount: 0 })).toBe(
      'getting-started',
    );
  });

  test('returns "getting-started" when profiles and documents exist but no correlations', () => {
    expect(getDashboardUserStage({ profileCount: 1, correlationCount: 0, documentCount: 3 })).toBe(
      'getting-started',
    );
  });

  test('returns "active" when all counts are positive', () => {
    expect(getDashboardUserStage({ profileCount: 1, correlationCount: 5, documentCount: 3 })).toBe(
      'active',
    );
  });

  test('returns "active" with large counts', () => {
    expect(
      getDashboardUserStage({ profileCount: 3, correlationCount: 100, documentCount: 50 }),
    ).toBe('active');
  });
});
