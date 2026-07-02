import { describe, expect } from 'vitest';
import { extractDefaultsFromSchema, getPropertyDefault } from './schema-defaults.ts';

const TEST_NUMBER_DEFAULT: number = 42;

describe('getPropertyDefault - explicit and primitive defaults', () => {
  test('returns explicit default when provided', () => {
    expect(getPropertyDefault({ type: 'string', default: 'hello' })).toBe('hello');
    expect(getPropertyDefault({ type: 'number', default: TEST_NUMBER_DEFAULT })).toBe(
      TEST_NUMBER_DEFAULT,
    );
    expect(getPropertyDefault({ type: 'boolean', default: true })).toBe(true);
  });

  test('returns empty string for string type', () => {
    expect(getPropertyDefault({ type: 'string' })).toBe('');
  });

  test('returns 0 for number type', () => {
    expect(getPropertyDefault({ type: 'number' })).toBe(0);
  });

  test('returns 0 for integer type', () => {
    expect(getPropertyDefault({ type: 'integer' })).toBe(0);
  });

  test('returns false for boolean type', () => {
    expect(getPropertyDefault({ type: 'boolean' })).toBe(false);
  });

  test('returns empty array for array type', () => {
    expect(getPropertyDefault({ type: 'array' })).toEqual([]);
  });
});

describe('getPropertyDefault - objects and complex types', () => {
  test('returns empty object for object type without properties', () => {
    expect(getPropertyDefault({ type: 'object' })).toEqual({});
  });

  test('extracts nested defaults for object type with properties', () => {
    const property = {
      type: 'object',
      properties: {
        name: { type: 'string' },
        age: { type: 'number' },
      },
    };
    expect(getPropertyDefault(property)).toEqual({ name: '', age: 0 });
  });

  test('returns null for unknown type', () => {
    expect(getPropertyDefault({ type: 'unknown' })).toBeNull();
  });

  test('handles array item schemas the same as property schemas', () => {
    expect(getPropertyDefault({ type: 'string', default: 'item' })).toBe('item');
    expect(getPropertyDefault({ type: 'string' })).toBe('');
    expect(getPropertyDefault({ type: 'number' })).toBe(0);
    expect(getPropertyDefault({ type: 'boolean' })).toBe(false);
  });

  test('extracts defaults for object item schemas', () => {
    const itemSchema = {
      type: 'object',
      properties: {
        id: { type: 'number' },
        label: { type: 'string' },
      },
    };
    expect(getPropertyDefault(itemSchema)).toEqual({ id: 0, label: '' });
  });

  test('returns null for unknown item type', () => {
    expect(getPropertyDefault({ type: 'custom' })).toBeNull();
  });
});

describe('extractDefaultsFromSchema - basic', () => {
  test('returns empty object for non-object schema', () => {
    expect(extractDefaultsFromSchema({ type: 'string' })).toEqual({});
    expect(extractDefaultsFromSchema({ type: 'array' })).toEqual({});
  });

  test('returns empty object for schema without properties', () => {
    expect(extractDefaultsFromSchema({ type: 'object' })).toEqual({});
  });

  test('extracts defaults for simple properties', () => {
    const schema = {
      type: 'object',
      properties: {
        name: { type: 'string' },
        age: { type: 'number' },
        active: { type: 'boolean' },
      },
    };
    expect(extractDefaultsFromSchema(schema)).toEqual({
      name: '',
      age: 0,
      active: false,
    });
  });
});

describe('extractDefaultsFromSchema - complex', () => {
  test('uses explicit defaults when provided', () => {
    const schema = {
      type: 'object',
      properties: {
        name: { type: 'string', default: 'John' },
        count: { type: 'number', default: 10 },
      },
    };
    expect(extractDefaultsFromSchema(schema)).toEqual({
      name: 'John',
      count: 10,
    });
  });

  test('handles nested objects', () => {
    const schema = {
      type: 'object',
      properties: {
        person: {
          type: 'object',
          properties: {
            name: { type: 'string' },
            age: { type: 'number' },
          },
        },
      },
    };
    expect(extractDefaultsFromSchema(schema)).toEqual({
      person: { name: '', age: 0 },
    });
  });

  test('handles mixed property types', () => {
    const schema = {
      type: 'object',
      properties: {
        title: { type: 'string', default: 'Untitled' },
        tags: { type: 'array' },
        metadata: {
          type: 'object',
          properties: {
            version: { type: 'string', default: '1.0.0' },
          },
        },
      },
    };
    expect(extractDefaultsFromSchema(schema)).toEqual({
      title: 'Untitled',
      tags: [],
      metadata: { version: '1.0.0' },
    });
  });
});
