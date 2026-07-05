import { describe, expect } from 'vitest';
import { listSearchSchema } from './list-search-schema.ts';

describe('listSearchSchema', () => {
  test('produces defaults from first sort field and asc direction', () => {
    const schema = listSearchSchema(['name', 'keywords']);
    expect(schema.parse({})).toEqual({ page: 1, sort: 'name', dir: 'asc' });
  });

  test('accepts explicit defaults', () => {
    const schema = listSearchSchema(['posted_at', 'company'], {
      sort: 'company',
      dir: 'desc',
    });
    expect(schema.parse({})).toEqual({ page: 1, sort: 'company', dir: 'desc' });
  });

  test('preserves valid values from input', () => {
    const schema = listSearchSchema(['name', 'size']);
    expect(schema.parse({ page: 3, sort: 'size', dir: 'desc' })).toEqual({
      page: 3,
      sort: 'size',
      dir: 'desc',
    });
  });

  test('falls back to defaults for invalid sort field', () => {
    const schema = listSearchSchema(['name', 'size']);
    expect(schema.parse({ sort: 'invalid' })).toEqual({ page: 1, sort: 'name', dir: 'asc' });
  });

  test('falls back to defaults for invalid direction', () => {
    const schema = listSearchSchema(['name', 'size']);
    expect(schema.parse({ dir: 'sideways' })).toEqual({ page: 1, sort: 'name', dir: 'asc' });
  });

  test('clamps page to minimum of 1', () => {
    const schema = listSearchSchema(['name']);
    expect(() => schema.parse({ page: 0 })).toThrow();
    expect(() => schema.parse({ page: -5 })).toThrow();
  });

  test('rejects non-integer page values', () => {
    const schema = listSearchSchema(['name']);
    expect(() => schema.parse({ page: 1.5 })).toThrow();
  });
});
