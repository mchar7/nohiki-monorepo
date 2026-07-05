import { describe, expect } from 'vitest';
import { formatSalaryRange } from './salary-format.ts';

describe('formatSalaryRange – null/undefined inputs', () => {
  test('returns null when both min and max are null', () => {
    expect(formatSalaryRange({ min: null, max: null })).toBeNull();
  });

  test('returns null when both min and max are undefined', () => {
    expect(formatSalaryRange({})).toBeNull();
  });

  test('returns null when min is null and max is undefined', () => {
    expect(formatSalaryRange({ min: null })).toBeNull();
  });
});

describe('formatSalaryRange – compact format', () => {
  test('formats full range with USD compact', () => {
    expect(formatSalaryRange({ min: 120_000, max: 160_000, currency: 'USD', compact: true })).toBe(
      '$120k – $160k',
    );
  });

  test('formats only min compact', () => {
    expect(formatSalaryRange({ min: 80_000, currency: 'USD', compact: true })).toBe('$80k+');
  });

  test('formats only max compact', () => {
    expect(formatSalaryRange({ max: 100_000, currency: 'USD', compact: true })).toBe('Up to $100k');
  });

  test('does not append frequency suffix without explicit frequency', () => {
    expect(formatSalaryRange({ min: 90_000, max: 120_000, currency: 'USD', compact: true })).toBe(
      '$90k – $120k',
    );
  });
});

describe('formatSalaryRange – full format', () => {
  test('formats full range with USD annually', () => {
    expect(
      formatSalaryRange({ min: 120_000, max: 160_000, currency: 'USD', frequency: 'ANNUALLY' }),
    ).toBe('$120,000 – $160,000/yr');
  });

  test('formats only min with frequency', () => {
    expect(formatSalaryRange({ min: 120_000, currency: 'USD', frequency: 'ANNUALLY' })).toBe(
      '$120,000+/yr',
    );
  });

  test('formats only max with frequency', () => {
    expect(formatSalaryRange({ max: 150_000, currency: 'USD', frequency: 'ANNUALLY' })).toBe(
      'Up to $150,000/yr',
    );
  });

  test('formats monthly frequency', () => {
    expect(formatSalaryRange({ min: 5000, max: 8000, currency: 'USD', frequency: 'MONTHLY' })).toBe(
      '$5,000 – $8,000/mo',
    );
  });

  test('formats hourly frequency', () => {
    expect(formatSalaryRange({ min: 25, max: 40, currency: 'USD', frequency: 'HOURLY' })).toBe(
      '$25 – $40/hr',
    );
  });
});

describe('formatSalaryRange – currency support', () => {
  test('formats CAD', () => {
    expect(formatSalaryRange({ min: 100_000, max: 130_000, currency: 'CAD' })).toBe(
      'CA$100,000 – CA$130,000',
    );
  });

  test('formats EUR', () => {
    expect(formatSalaryRange({ min: 60_000, max: 90_000, currency: 'EUR' })).toBe(
      '€60,000 – €90,000',
    );
  });

  test('formats GBP', () => {
    expect(formatSalaryRange({ min: 50_000, max: 75_000, currency: 'GBP' })).toBe(
      '£50,000 – £75,000',
    );
  });

  test('falls back to USD symbol for unknown currency', () => {
    expect(formatSalaryRange({ min: 50_000, currency: 'XYZ' })).toBe('$50,000+');
  });
});

describe('formatSalaryRange – edge cases', () => {
  test('handles 0 as a valid min value', () => {
    expect(formatSalaryRange({ min: 0, max: 50_000, currency: 'USD' })).toBe('$0 – $50,000');
  });

  test('handles min=0 and max=0', () => {
    expect(formatSalaryRange({ min: 0, max: 0, currency: 'USD' })).toBe('$0 – $0');
  });

  test('handles very large numbers in compact mode', () => {
    expect(
      formatSalaryRange({ min: 1_000_000, max: 2_000_000, currency: 'USD', compact: true }),
    ).toBe('$1000k – $2000k');
  });

  test('handles fractional thousands in compact mode', () => {
    expect(formatSalaryRange({ min: 125_500, currency: 'USD', compact: true })).toBe('$125.5k+');
  });

  test('omits frequency suffix when frequency is null', () => {
    expect(formatSalaryRange({ min: 80_000, max: 100_000, currency: 'USD', frequency: null })).toBe(
      '$80,000 – $100,000',
    );
  });

  test('omits frequency suffix for unknown frequency string', () => {
    expect(formatSalaryRange({ min: 80_000, currency: 'USD', frequency: 'WEEKLY' })).toBe(
      '$80,000+',
    );
  });
});
