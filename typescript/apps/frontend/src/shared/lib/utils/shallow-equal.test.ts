import { describe, expect } from 'vitest';
import { shallowEqual } from './shallow-equal.ts';

const SAMPLE_NUMBER = 42;

describe('shallowEqual - fast path: reference and primitive equality', () => {
  test('returns true for identical primitive numbers', () => {
    expect(shallowEqual(SAMPLE_NUMBER, SAMPLE_NUMBER)).toBe(true);
  });

  test('returns true for identical primitive strings', () => {
    expect(shallowEqual('hello', 'hello')).toBe(true);
  });

  test('returns true for the same object reference', () => {
    const obj = { a: 1 };
    expect(shallowEqual(obj, obj)).toBe(true);
  });

  test('returns true for NaN compared with NaN via Object.is semantics', () => {
    expect(shallowEqual(Number.NaN, Number.NaN)).toBe(true);
  });

  test('returns false for -0 and +0 via Object.is semantics', () => {
    expect(shallowEqual(-0, 0)).toBe(false);
  });

  test('returns false for distinct primitive numbers', () => {
    expect(shallowEqual(1, 2)).toBe(false);
  });
});

describe('shallowEqual - null and undefined handling', () => {
  test('returns true for both null', () => {
    expect(shallowEqual(null, null)).toBe(true);
  });

  test('returns true for both undefined', () => {
    expect(shallowEqual(undefined, undefined)).toBe(true);
  });

  test('returns false for null compared with an object', () => {
    expect(shallowEqual(null, { a: 1 })).toBe(false);
    expect(shallowEqual({ a: 1 }, null)).toBe(false);
  });

  test('returns false for undefined compared with an object', () => {
    expect(shallowEqual(undefined, { a: 1 })).toBe(false);
    expect(shallowEqual({ a: 1 }, undefined)).toBe(false);
  });
});

describe('shallowEqual - plain object comparison', () => {
  test('returns true for two empty objects', () => {
    expect(shallowEqual({}, {})).toBe(true);
  });

  test('returns true for objects with identical primitive values', () => {
    expect(shallowEqual({ x: 1, y: 'two', z: true }, { x: 1, y: 'two', z: true })).toBe(true);
  });

  test('returns false for objects with the same keys but different values', () => {
    expect(shallowEqual({ x: 1 }, { x: 2 })).toBe(false);
  });

  test('returns false for objects with different key counts', () => {
    expect(shallowEqual({ x: 1, y: 2 }, { x: 1 })).toBe(false);
  });

  test('returns false when b has extra keys not present in a', () => {
    expect(shallowEqual({ x: 1 }, { x: 1, y: 2 })).toBe(false);
  });

  test('returns false for objects with same key count but different key names', () => {
    expect(shallowEqual({ a: 1 }, { b: 1 })).toBe(false);
  });
});

describe('shallowEqual - shallow comparison boundaries', () => {
  test('returns false for nested objects with equal structure but different references', () => {
    const a = { nested: { value: 1 } };
    const b = { nested: { value: 1 } };
    // Nested objects are distinct references; shallowEqual does not recurse
    expect(shallowEqual(a, b)).toBe(false);
  });

  test('returns true for nested objects when both sides share the same nested reference', () => {
    const shared = { value: 1 };
    expect(shallowEqual({ nested: shared }, { nested: shared })).toBe(true);
  });
});
