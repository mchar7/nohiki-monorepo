import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import type { JobCorrelationResponse } from '@/shared/api';
import { aggregateCorrelationsByDate, isWithinWeek, withMovingAverage } from './utils.ts';

function correlation(created_at: string): JobCorrelationResponse {
  return {
    id: created_at,
    pref_id: 'pref-1',
    listing_id: 'listing-1',
    fit_score: 80,
    status: 'EVALUATED',
    score_breakdown: {},
    listing_title: 'Engineer',
    listing_company: 'Acme',
    listing_url: 'https://example.com',
    listing_location: 'Remote',
    created_at,
    updated_at: created_at,
  };
}

const FIXED_NOW: Date = new Date('2025-03-26T12:00:00.000Z');
const DAYS_IN_RANGE: number = 3;
const MOVING_AVG_WINDOW: number = 3;

describe('isWithinWeek', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test('returns true for a date within the last 7 days', () => {
    expect(isWithinWeek('2025-03-25T00:00:00.000Z')).toBe(true);
    expect(isWithinWeek('2025-03-20T00:00:00.000Z')).toBe(true);
  });
  test('returns false for a date older than 7 days', () => {
    expect(isWithinWeek('2025-03-18T00:00:00.000Z')).toBe(false);
    expect(isWithinWeek('2025-01-01T00:00:00.000Z')).toBe(false);
  });
});

describe('aggregateCorrelationsByDate', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test('creates entries for each day in the range', () => {
    const result = aggregateCorrelationsByDate([], DAYS_IN_RANGE);
    expect(result).toHaveLength(DAYS_IN_RANGE);
    expect(result.map((r) => r.date)).toEqual(['2025-03-24', '2025-03-25', '2025-03-26']);
  });

  test('counts correlations on matching dates', () => {
    const correlations = [
      correlation('2025-03-25T10:00:00.000Z'),
      correlation('2025-03-25T15:00:00.000Z'),
      correlation('2025-03-26T08:00:00.000Z'),
    ];

    const result = aggregateCorrelationsByDate(correlations, DAYS_IN_RANGE);
    expect(result.find((r) => r.date === '2025-03-25')?.matches).toBe(2);
    expect(result.find((r) => r.date === '2025-03-26')?.matches).toBe(1);
    expect(result.find((r) => r.date === '2025-03-24')?.matches).toBe(0);
  });

  test('ignores correlations outside the date range', () => {
    const correlations = [correlation('2025-01-01T10:00:00.000Z')];
    const result = aggregateCorrelationsByDate(correlations, DAYS_IN_RANGE);
    expect(result.every((r) => r.matches === 0)).toBe(true);
  });
});

describe('withMovingAverage', () => {
  test('returns data unchanged when fewer than 5 points', () => {
    const data = [
      { date: '2025-01-01', matches: 10 },
      { date: '2025-01-02', matches: 20 },
    ];
    expect(withMovingAverage(data).every((p) => p.trend === undefined)).toBe(true);
  });

  test('adds trend values for 5+ points', () => {
    const data = Array.from({ length: 7 }, (_, i) => ({
      date: `2025-01-0${i + 1}`,
      matches: 10,
    }));
    const result = withMovingAverage(data, MOVING_AVG_WINDOW);
    expect(result.every((p) => typeof p.trend === 'number')).toBe(true);
    expect(result.at(-1)?.trend).toBe(10);
  });
});
