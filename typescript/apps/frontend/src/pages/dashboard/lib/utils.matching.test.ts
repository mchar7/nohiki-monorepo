import { describe, expect } from 'vitest';
import { getProgressClassName, getScoreClassName, getTopMatch } from './utils.ts';

/** Score threshold boundary values used in assertions. */
const SCORE_EXCELLENT: number = 85;
const SCORE_EXCELLENT_MAX: number = 100;
const SCORE_GOOD: number = 70;
const SCORE_GOOD_MAX: number = 84;
const SCORE_FAIR: number = 50;
const SCORE_FAIR_MAX: number = 69;
const SCORE_LOW_MAX: number = 49;

describe('getTopMatch', () => {
  test('returns null for empty array', () => {
    expect(getTopMatch([])).toBeNull();
  });

  test('returns the single item', () => {
    expect(getTopMatch([{ fit_score: 75, id: 'a' }])).toEqual({ fit_score: 75, id: 'a' });
  });

  test('returns the item with highest fit_score', () => {
    const items = [
      { fit_score: 60, id: 'a' },
      { fit_score: 95, id: 'b' },
      { fit_score: 80, id: 'c' },
    ];
    expect(getTopMatch(items)).toEqual({ fit_score: 95, id: 'b' });
  });

  test('returns first occurrence on tied scores', () => {
    const items = [
      { fit_score: 90, id: 'first' },
      { fit_score: 90, id: 'second' },
    ];
    expect(getTopMatch(items)?.id).toBe('first');
  });
});

describe('getScoreClassName', () => {
  test('returns excellent for scores >= 85', () => {
    expect(getScoreClassName(SCORE_EXCELLENT)).toBe('match-score-excellent');
    expect(getScoreClassName(SCORE_EXCELLENT_MAX)).toBe('match-score-excellent');
  });
  test('returns good for scores >= 70 and < 85', () => {
    expect(getScoreClassName(SCORE_GOOD)).toBe('match-score-good');
    expect(getScoreClassName(SCORE_GOOD_MAX)).toBe('match-score-good');
  });
  test('returns fair for scores >= 50 and < 70', () => {
    expect(getScoreClassName(SCORE_FAIR)).toBe('match-score-fair');
    expect(getScoreClassName(SCORE_FAIR_MAX)).toBe('match-score-fair');
  });
  test('returns low for scores < 50', () => {
    expect(getScoreClassName(0)).toBe('match-score-low');
    expect(getScoreClassName(SCORE_LOW_MAX)).toBe('match-score-low');
  });
});

describe('getProgressClassName', () => {
  test('returns excellent for scores >= 85', () => {
    expect(getProgressClassName(SCORE_EXCELLENT)).toBe('match-progress-excellent');
    expect(getProgressClassName(SCORE_EXCELLENT_MAX)).toBe('match-progress-excellent');
  });
  test('returns good for scores >= 70 and < 85', () => {
    expect(getProgressClassName(SCORE_GOOD)).toBe('match-progress-good');
    expect(getProgressClassName(SCORE_GOOD_MAX)).toBe('match-progress-good');
  });
  test('returns fair for scores >= 50 and < 70', () => {
    expect(getProgressClassName(SCORE_FAIR)).toBe('match-progress-fair');
    expect(getProgressClassName(SCORE_FAIR_MAX)).toBe('match-progress-fair');
  });
  test('returns low for scores < 50', () => {
    expect(getProgressClassName(0)).toBe('match-progress-low');
    expect(getProgressClassName(SCORE_LOW_MAX)).toBe('match-progress-low');
  });
});
