import { describe, expect, it } from 'vitest';
import { ALPHA2_TO_ALPHA3, resolveCountry } from './geo';

const SUPPORTED_COUNTRY_COUNT = 14;

describe('ALPHA2_TO_ALPHA3', () => {
  it('has exactly 14 entries', () => {
    expect(Object.keys(ALPHA2_TO_ALPHA3)).toHaveLength(SUPPORTED_COUNTRY_COUNT);
  });

  it.each([
    ['US', 'USA'],
    ['CA', 'CAN'],
    ['GB', 'GBR'],
    ['DE', 'DEU'],
    ['FR', 'FRA'],
    ['NL', 'NLD'],
    ['IE', 'IRL'],
    ['CH', 'CHE'],
    ['AU', 'AUS'],
    ['NZ', 'NZL'],
    ['SG', 'SGP'],
    ['IN', 'IND'],
    ['AE', 'ARE'],
    ['IL', 'ISR'],
  ] as const)('maps %s → %s', (alpha2, expected) => {
    expect(ALPHA2_TO_ALPHA3[alpha2]).toBe(expected);
  });
});

describe('resolveCountry', () => {
  it('resolves a known alpha-2 code', () => {
    expect(resolveCountry('US')).toBe('USA');
  });

  it('resolves GB to GBR', () => {
    expect(resolveCountry('GB')).toBe('GBR');
  });

  it('defaults to USA for undefined input', () => {
    expect(resolveCountry(undefined)).toBe('USA');
  });

  it('defaults to USA for an unmapped alpha-2 code', () => {
    expect(resolveCountry('XX')).toBe('USA');
  });

  it('defaults to USA for empty string', () => {
    expect(resolveCountry('')).toBe('USA');
  });
});
