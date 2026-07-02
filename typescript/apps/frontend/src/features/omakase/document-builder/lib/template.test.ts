import { describe, expect } from 'vitest';
import { getUIHints, shouldRenderAsFields } from './template.ts';

const TEST_COLUMNS_COUNT: number = 3;

describe('getUIHints - single hints', () => {
  test('extracts direction hint', () => {
    const schema = { 'x-direction': 'row' };

    const hints = getUIHints(schema);

    expect(hints.direction).toBe('row');
  });

  test('extracts fieldNames hint', () => {
    const schema = { 'x-field-names': ['First', 'Second'] };

    const hints = getUIHints(schema);

    expect(hints.fieldNames).toEqual(['First', 'Second']);
  });

  test('extracts placeholder hint', () => {
    const schema = { 'x-placeholder': 'Enter value...' };

    const hints = getUIHints(schema);

    expect(hints.placeholder).toBe('Enter value...');
  });

  test('extracts widget hint', () => {
    const schema = { 'x-widget': 'textarea' };

    const hints = getUIHints(schema);

    expect(hints.widget).toBe('textarea');
  });

  test('extracts columns hint', () => {
    const schema = { 'x-columns': 2 };

    const hints = getUIHints(schema);

    expect(hints.columns).toBe(2);
  });
});

describe('getUIHints - boolean and combined hints', () => {
  test('extracts showItemLabels hint', () => {
    const schema = { 'x-show-item-labels': true };

    const hints = getUIHints(schema);

    expect(hints.showItemLabels).toBe(true);
  });

  test('extracts renderAsFields hint', () => {
    const schema = { 'x-render-as-fields': true };

    const hints = getUIHints(schema);

    expect(hints.renderAsFields).toBe(true);
  });

  test('returns empty object for schema without hints', () => {
    const schema = { type: 'string' };

    const hints = getUIHints(schema);

    expect(hints).toEqual({});
  });

  test('extracts multiple hints', () => {
    const schema = {
      'x-direction': 'column',
      'x-placeholder': 'Test',
      'x-columns': TEST_COLUMNS_COUNT,
    };

    const hints = getUIHints(schema);

    expect(hints.direction).toBe('column');
    expect(hints.placeholder).toBe('Test');
    expect(hints.columns).toBe(TEST_COLUMNS_COUNT);
  });
});

describe('shouldRenderAsFields', () => {
  test('returns true for schema with prefixItems', () => {
    const schema = { prefixItems: [{ type: 'string' }] };

    expect(shouldRenderAsFields(schema)).toBe(true);
  });

  test('returns true for maxItems <= 3', () => {
    const schema = { maxItems: 2 };

    expect(shouldRenderAsFields(schema)).toBe(true);
  });

  test('returns true for maxItems === 3', () => {
    const schema = { maxItems: 3 };

    expect(shouldRenderAsFields(schema)).toBe(true);
  });

  test('returns false for maxItems > 3', () => {
    const schema = { maxItems: 4 };

    expect(shouldRenderAsFields(schema)).toBe(false);
  });

  test('returns false for schema without prefixItems or maxItems', () => {
    const schema = { type: 'array' };

    expect(shouldRenderAsFields(schema)).toBe(false);
  });
});
