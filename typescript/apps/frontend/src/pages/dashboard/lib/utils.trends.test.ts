import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { computeStatTrends, computeTrendSummary } from './utils.ts';

/** Sunday remapped to 7 for Monday-based week math. */
const SUNDAY_ISO_DAY: number = 7;
const DAYS_PER_WEEK: number = 7;
/** Small ms offsets to create distinct timestamps within a given day. */
const MS_OFFSET_1: number = 1000;
const MS_OFFSET_2: number = 2000;
const MS_OFFSET_3: number = 3000;
const WEEKS_AGO_3: number = 21;
const FIXED_NOW: Date = new Date('2025-03-26T12:00:00.000Z');

/** Returns Monday 00:00 of the week containing `date` (ISO Monday-based). */
function getMonday(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay();
  const diff = (day === 0 ? SUNDAY_ISO_DAY : day) - 1;
  d.setDate(d.getDate() - diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

describe('computeTrendSummary', () => {
  test('returns steady for empty data', () => {
    expect(computeTrendSummary([])).toEqual({
      direction: 'steady',
      percentChange: 0,
      label: '→ Steady',
    });
  });

  test('returns steady for a single data point', () => {
    expect(computeTrendSummary([{ date: '2025-01-01', count: 10 }]).direction).toBe('steady');
  });

  test('returns up for increasing data', () => {
    const data = [
      { date: '2025-01-01', count: 1 },
      { date: '2025-01-02', count: 2 },
      { date: '2025-01-03', count: 5 },
      { date: '2025-01-04', count: 10 },
    ];
    const result = computeTrendSummary(data);
    expect(result).toEqual({ direction: 'up', percentChange: 400, label: '↑ 400% more matches' });
  });

  test('returns down for decreasing data', () => {
    const data = [
      { date: '2025-01-01', count: 10 },
      { date: '2025-01-02', count: 8 },
      { date: '2025-01-03', count: 2 },
      { date: '2025-01-04', count: 1 },
    ];
    const result = computeTrendSummary(data);
    expect(result).toEqual({ direction: 'down', percentChange: 83, label: '↓ 83% fewer matches' });
  });

  test('returns steady when change is below 5% threshold', () => {
    const data = [
      { date: '2025-01-01', count: 50 },
      { date: '2025-01-02', count: 50 },
      { date: '2025-01-03', count: 51 },
      { date: '2025-01-04', count: 50 },
    ];
    expect(computeTrendSummary(data).direction).toBe('steady');
  });

  test('returns steady when all counts are zero', () => {
    const data = [
      { date: '2025-01-01', count: 0 },
      { date: '2025-01-02', count: 0 },
      { date: '2025-01-03', count: 0 },
      { date: '2025-01-04', count: 0 },
    ];
    expect(computeTrendSummary(data).direction).toBe('steady');
  });

  test('handles previous period zero with current activity as 100% up', () => {
    const data = [
      { date: '2025-01-01', count: 0 },
      { date: '2025-01-02', count: 0 },
      { date: '2025-01-03', count: 5 },
      { date: '2025-01-04', count: 3 },
    ];
    const result = computeTrendSummary(data);
    expect(result).toEqual({ direction: 'up', percentChange: 100, label: '↑ 100% more matches' });
  });

  test('handles odd number of data points', () => {
    const data = [
      { date: '2025-01-01', count: 2 },
      { date: '2025-01-02', count: 3 },
      { date: '2025-01-03', count: 10 },
      { date: '2025-01-04', count: 10 },
      { date: '2025-01-05', count: 10 },
    ];
    expect(computeTrendSummary(data).direction).toBe('up');
  });
});

function buildItems(base: Date, ...offsets: number[]): { created_at: string }[] {
  return offsets.map((ms) => ({ created_at: new Date(base.getTime() + ms).toISOString() }));
}

describe('computeStatTrends — week comparisons', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test('returns trends spanning two weeks', () => {
    const curMon = getMonday(FIXED_NOW);
    const prevMon = new Date(curMon);
    prevMon.setDate(prevMon.getDate() - DAYS_PER_WEEK);

    const correlations = [
      ...buildItems(prevMon, MS_OFFSET_1, MS_OFFSET_2),
      ...buildItems(curMon, MS_OFFSET_1, MS_OFFSET_2, MS_OFFSET_3),
    ];
    const documents = [...buildItems(prevMon, MS_OFFSET_1), ...buildItems(curMon, MS_OFFSET_1)];

    const result = computeStatTrends(correlations, documents);
    expect(result.jobMatches).toEqual({ direction: 'up', delta: 1 });
    expect(result.documents).toEqual({ direction: 'steady', delta: 0 });
  });

  test('returns unavailable when all items are in current week only', () => {
    const curMon = getMonday(FIXED_NOW);
    const correlations = buildItems(curMon, MS_OFFSET_1, MS_OFFSET_2);

    const result = computeStatTrends(correlations, []);
    expect(result.jobMatches).toEqual({ direction: 'unavailable', delta: 0 });
    expect(result.documents).toEqual({ direction: 'steady', delta: 0 });
  });

  test('returns steady for empty arrays', () => {
    const result = computeStatTrends([], []);
    expect(result.jobMatches).toEqual({ direction: 'steady', delta: 0 });
    expect(result.documents).toEqual({ direction: 'steady', delta: 0 });
  });
});

describe('computeStatTrends — edge cases', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FIXED_NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test('returns down when previous week had more items', () => {
    const curMon = getMonday(FIXED_NOW);
    const prevMon = new Date(curMon);
    prevMon.setDate(prevMon.getDate() - DAYS_PER_WEEK);

    const correlations = [
      ...buildItems(prevMon, MS_OFFSET_1, MS_OFFSET_2, MS_OFFSET_3),
      ...buildItems(curMon, MS_OFFSET_1),
    ];
    expect(computeStatTrends(correlations, []).jobMatches).toEqual({
      direction: 'down',
      delta: -2,
    });
  });

  test('ignores items from 3+ weeks ago (only affects unavailable detection)', () => {
    const curMon = getMonday(FIXED_NOW);
    const threeWeeksAgo = new Date(curMon);
    threeWeeksAgo.setDate(threeWeeksAgo.getDate() - WEEKS_AGO_3);

    const correlations = buildItems(threeWeeksAgo, MS_OFFSET_1);
    expect(computeStatTrends(correlations, []).jobMatches).toEqual({
      direction: 'steady',
      delta: 0,
    });
  });
});
