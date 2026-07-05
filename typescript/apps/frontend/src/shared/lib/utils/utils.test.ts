import { describe, expect } from 'vitest';
import { cn, sanitizeData } from './utils.ts';

/** Numeric primitive used to test sanitizeData pass-through */
const TEST_PRIMITIVE_NUMBER: number = 123;
const TEST_SPARSE_VALUE_A: number = 1;
const TEST_SPARSE_VALUE_B: number = 2;
const TEST_SPARSE_VALUE_C: number = 3;
/** Sample array with sparse nulls for sanitizeData filtering tests */
const TEST_SPARSE_ARRAY: (number | null | undefined)[] = [
  TEST_SPARSE_VALUE_A,
  null,
  TEST_SPARSE_VALUE_B,
  undefined,
  TEST_SPARSE_VALUE_C,
];
const TEST_SPARSE_ARRAY_FILTERED: number[] = [
  TEST_SPARSE_VALUE_A,
  TEST_SPARSE_VALUE_B,
  TEST_SPARSE_VALUE_C,
];

describe('cn', () => {
  test('merges class names', () => {
    expect(cn('foo', 'bar')).toBe('foo bar');
  });

  test('handles conditional classes', () => {
    expect(cn('foo', false, 'baz')).toBe('foo baz');
  });

  test('merges tailwind classes correctly', () => {
    expect(cn('p-4', 'p-2')).toBe('p-2');
  });

  test('handles arrays', () => {
    expect(cn(['foo', 'bar'])).toBe('foo bar');
  });

  test('handles undefined and null', () => {
    expect(cn('foo', undefined, null, 'bar')).toBe('foo bar');
  });

  test('handles objects', () => {
    expect(cn({ foo: true, bar: false })).toBe('foo');
  });
});

describe('sanitizeData - null and undefined removal', () => {
  test('removes null values', () => {
    const input = { a: 1, b: null, c: 'test' };
    expect(sanitizeData(input)).toEqual({ a: 1, c: 'test' });
  });

  test('removes undefined values', () => {
    const input = { a: 1, b: undefined, c: 'test' };
    expect(sanitizeData(input)).toEqual({ a: 1, c: 'test' });
  });

  test('preserves empty strings by default', () => {
    const input = { a: '', b: 'test' };
    expect(sanitizeData(input)).toEqual({ a: '', b: 'test' });
  });

  test('removes empty strings when removeEmptyStrings is true', () => {
    const input = { a: '', b: 'test' };
    expect(sanitizeData(input, true)).toEqual({ b: 'test' });
  });

  test('returns undefined for null input', () => {
    expect(sanitizeData(null)).toBeUndefined();
  });

  test('returns undefined for undefined input', () => {
    expect(sanitizeData(undefined)).toBeUndefined();
  });

  test('preserves primitive values', () => {
    expect(sanitizeData('string')).toBe('string');
    expect(sanitizeData(TEST_PRIMITIVE_NUMBER)).toBe(TEST_PRIMITIVE_NUMBER);
    expect(sanitizeData(true)).toBe(true);
  });
});

describe('sanitizeData - nested structures and arrays', () => {
  test('handles nested objects', () => {
    const input = {
      nested: { a: 1, b: null },
      other: 'value',
    };
    expect(sanitizeData(input)).toEqual({
      nested: { a: 1 },
      other: 'value',
    });
  });

  test('handles arrays', () => {
    expect(sanitizeData(TEST_SPARSE_ARRAY)).toEqual(TEST_SPARSE_ARRAY_FILTERED);
  });

  test('handles arrays with removeEmptyStrings', () => {
    const input = ['a', '', 'b'];
    expect(sanitizeData(input, true)).toEqual(['a', 'b']);
  });

  test('handles deeply nested structures', () => {
    const input = {
      level1: {
        level2: {
          level3: {
            value: 'test',
            nullValue: null,
          },
        },
      },
    };
    expect(sanitizeData(input)).toEqual({
      level1: {
        level2: {
          level3: {
            value: 'test',
          },
        },
      },
    });
  });
});
