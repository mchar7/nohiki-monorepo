import { describe, expect } from 'vitest';
import { parseMatchExplanation } from './parseMatchExplanation.ts';

describe('parseMatchExplanation — valid input', () => {
  test('parses standard format with both strengths and concerns', () => {
    const input =
      'Strengths: skill_match (+0.5), location_fit (+0.3). Concerns: experience_gap (-0.2).';
    const result = parseMatchExplanation(input);

    expect(result.strengths).toEqual(['Skill Match', 'Location Fit']);
    expect(result.concerns).toEqual(['Experience Gap']);
  });

  test('parses strengths only (no concerns section)', () => {
    const input = 'Strengths: skill_match (+0.5), remote_work (+0.4).';
    const result = parseMatchExplanation(input);

    expect(result.strengths).toEqual(['Skill Match', 'Remote Work']);
    expect(result.concerns).toEqual([]);
  });

  test('parses concerns only (no strengths section)', () => {
    const input = 'Concerns: salary_mismatch (-0.3).';
    const result = parseMatchExplanation(input);

    expect(result.strengths).toEqual([]);
    expect(result.concerns).toEqual(['Salary Mismatch']);
  });

  test('handles single-word factors', () => {
    const input = 'Strengths: location (+0.9). Concerns: salary (-0.4).';
    const result = parseMatchExplanation(input);

    expect(result.strengths).toEqual(['Location']);
    expect(result.concerns).toEqual(['Salary']);
  });

  test('handles multiple concerns', () => {
    const input =
      'Strengths: skill_match (+0.5). Concerns: experience_gap (-0.2), location_mismatch (-0.3).';
    const result = parseMatchExplanation(input);

    expect(result.strengths).toEqual(['Skill Match']);
    expect(result.concerns).toEqual(['Experience Gap', 'Location Mismatch']);
  });

  test('converts snake_case to Title Case correctly', () => {
    const input = 'Strengths: work_life_balance (+0.8), career_growth (+0.6).';
    const result = parseMatchExplanation(input);

    expect(result.strengths).toEqual(['Work Life Balance', 'Career Growth']);
  });
});

describe('parseMatchExplanation — edge cases', () => {
  test('returns empty arrays for null input', () => {
    const result = parseMatchExplanation(null);
    expect(result).toEqual({ strengths: [], concerns: [] });
  });

  test('returns empty arrays for undefined input', () => {
    const result = parseMatchExplanation(undefined);
    expect(result).toEqual({ strengths: [], concerns: [] });
  });

  test('returns empty arrays for empty string', () => {
    const result = parseMatchExplanation('');
    expect(result).toEqual({ strengths: [], concerns: [] });
  });

  test('returns empty arrays for whitespace-only string', () => {
    const result = parseMatchExplanation('   ');
    expect(result).toEqual({ strengths: [], concerns: [] });
  });

  test('handles malformed input without throwing', () => {
    const result = parseMatchExplanation('This is not a valid explanation string');
    expect(result).toEqual({ strengths: [], concerns: [] });
  });

  test('handles partial malformed input gracefully', () => {
    const result = parseMatchExplanation('Strengths: . Concerns: .');
    expect(result).toEqual({ strengths: [], concerns: [] });
  });
});
