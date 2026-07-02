import { describe, expect } from 'vitest';
import type { TemplateFamilyResponse } from '@/shared/api';

const TEST_DATASET_NAME_MAX_LENGTH: number = 100;
const TEST_DATASET_NAME_OVER_MAX_LENGTH: number = 101;
const TEST_NUMERIC_DATA: number = 123;
const TEST_ARRAY_VALUE_A: number = 1;
const TEST_ARRAY_VALUE_B: number = 2;
const TEST_ARRAY_VALUE_C: number = 3;
const TEST_ARRAY_VALUES: number[] = [TEST_ARRAY_VALUE_A, TEST_ARRAY_VALUE_B, TEST_ARRAY_VALUE_C];

import type { Dataset } from '../model/index.ts';
import {
  cloneDataset,
  findMostRecentDataset,
  generateUniqueDatasetName,
  getUniqueTemplates,
  sanitizeDatasetData,
  validateDatasetName,
  validateDatasetStructure,
} from './datasetService.ts';

const createMockDataset = (overrides: Partial<Dataset> = {}): Dataset => ({
  id: 'dataset-1',
  name: 'Test Dataset',
  templateVersionId: 'version-1',
  data: { title: 'Test' },
  createdAt: '2025-01-01T00:00:00Z',
  updatedAt: '2025-01-01T00:00:00Z',
  ...overrides,
});

const createMockTemplateFamily = (
  overrides: Partial<TemplateFamilyResponse> = {},
): TemplateFamilyResponse => ({
  id: 'family-1',
  namespace: 'default',
  name: 'Test Template',
  description: 'Test template',
  latest_version: null,
  ...overrides,
});

describe('datasetService - validateDatasetStructure', () => {
  test('returns true for valid objects', () => {
    expect(validateDatasetStructure({ key: 'value' })).toBe(true);
    expect(validateDatasetStructure({})).toBe(true);
  });

  test('returns false for null', () => {
    expect(validateDatasetStructure(null)).toBe(false);
  });

  test('returns false for arrays', () => {
    expect(validateDatasetStructure([])).toBe(false);
    expect(validateDatasetStructure(TEST_ARRAY_VALUES)).toBe(false);
  });

  test('returns false for primitives', () => {
    expect(validateDatasetStructure('string')).toBe(false);
    expect(validateDatasetStructure(TEST_NUMERIC_DATA)).toBe(false);
    expect(validateDatasetStructure(undefined)).toBe(false);
  });
});

describe('datasetService - sanitizeDatasetData', () => {
  test('returns empty object for invalid input', () => {
    expect(sanitizeDatasetData(null)).toEqual({});
    expect(sanitizeDatasetData('string')).toEqual({});
    expect(sanitizeDatasetData([])).toEqual({});
  });

  test('removes undefined values', () => {
    const input = { a: 1, b: undefined, c: 'test' };
    expect(sanitizeDatasetData(input)).toEqual({ a: 1, c: 'test' });
  });

  test('preserves null values', () => {
    const input = { a: null, b: 'test' };
    expect(sanitizeDatasetData(input)).toEqual({ a: null, b: 'test' });
  });

  test('preserves nested objects', () => {
    const input = { nested: { a: 1, b: 2 } };
    expect(sanitizeDatasetData(input)).toEqual({ nested: { a: 1, b: 2 } });
  });
});

describe('datasetService - cloneDataset', () => {
  test('creates a copy with default name suffix', () => {
    const original = createMockDataset({ name: 'My Dataset' });
    const cloned = cloneDataset(original);

    expect(cloned.name).toBe('My Dataset (Copy)');
    expect(cloned.templateVersionId).toBe(original.templateVersionId);
    expect(cloned.data).toEqual(original.data);
  });

  test('uses custom name when provided', () => {
    const original = createMockDataset();
    const cloned = cloneDataset(original, 'Custom Name');

    expect(cloned.name).toBe('Custom Name');
  });

  test('creates a shallow copy of data', () => {
    const original = createMockDataset({ data: { nested: { value: 1 } } });
    const cloned = cloneDataset(original);

    expect(cloned.data).toEqual(original.data);
    expect(cloned.data).not.toBe(original.data);
  });
});

describe('datasetService - findMostRecentDataset', () => {
  test('returns null for empty array', () => {
    expect(findMostRecentDataset([])).toBeNull();
  });

  test('returns the single dataset when only one exists', () => {
    const dataset = createMockDataset();
    expect(findMostRecentDataset([dataset])).toBe(dataset);
  });

  test('returns the most recently updated dataset', () => {
    const older = createMockDataset({ id: '1', updatedAt: '2025-01-01T00:00:00Z' });
    const newer = createMockDataset({ id: '2', updatedAt: '2025-06-01T00:00:00Z' });
    const oldest = createMockDataset({ id: '3', updatedAt: '2024-01-01T00:00:00Z' });

    expect(findMostRecentDataset([older, newer, oldest])).toBe(newer);
    expect(findMostRecentDataset([oldest, older, newer])).toBe(newer);
  });
});

describe('datasetService - getUniqueTemplates', () => {
  test('returns empty array for empty datasets', () => {
    const templates = [createMockTemplateFamily()];
    expect(getUniqueTemplates([], templates)).toEqual([]);
  });

  test('returns matching templates for datasets', () => {
    const template1 = createMockTemplateFamily({ id: 'family-1' });
    const template2 = createMockTemplateFamily({ id: 'family-2' });
    const templates = [template1, template2];

    const datasets = [
      createMockDataset({ templateVersionId: 'family-1' }),
      createMockDataset({ templateVersionId: 'family-1' }),
    ];

    const result = getUniqueTemplates(datasets, templates);
    expect(result).toHaveLength(1);
    expect(result[0]).toBe(template1);
  });

  test('filters out datasets with no matching template', () => {
    const template = createMockTemplateFamily({ id: 'family-1' });
    const datasets = [createMockDataset({ templateVersionId: 'non-existent' })];

    expect(getUniqueTemplates(datasets, [template])).toEqual([]);
  });
});

describe('datasetService - validateDatasetName', () => {
  test('returns valid for normal names', () => {
    expect(validateDatasetName('My Dataset')).toEqual({ isValid: true });
    expect(validateDatasetName('Resume v2')).toEqual({ isValid: true });
  });

  test('returns invalid for empty names', () => {
    const result = validateDatasetName('');
    expect(result.isValid).toBe(false);
    expect(result.error).toBe('Dataset name cannot be empty');
  });

  test('returns invalid for whitespace-only names', () => {
    const result = validateDatasetName('   ');
    expect(result.isValid).toBe(false);
    expect(result.error).toBe('Dataset name cannot be empty');
  });

  test('returns invalid for names over 100 characters', () => {
    const longName = 'a'.repeat(TEST_DATASET_NAME_OVER_MAX_LENGTH);
    const result = validateDatasetName(longName);
    expect(result.isValid).toBe(false);
    expect(result.error).toBe(
      `Dataset name must be ${TEST_DATASET_NAME_MAX_LENGTH} characters or less`,
    );
  });

  test('accepts names exactly 100 characters', () => {
    const exactName = 'a'.repeat(TEST_DATASET_NAME_MAX_LENGTH);
    expect(validateDatasetName(exactName)).toEqual({ isValid: true });
  });
});

describe('datasetService - generateUniqueDatasetName', () => {
  test('returns base name if no conflicts', () => {
    const datasets = [createMockDataset({ name: 'Other' })];
    expect(generateUniqueDatasetName('New Dataset', datasets)).toBe('New Dataset');
  });

  test('adds (1) suffix for first conflict', () => {
    const datasets = [createMockDataset({ name: 'My Dataset' })];
    expect(generateUniqueDatasetName('My Dataset', datasets)).toBe('My Dataset (1)');
  });

  test('increments suffix for multiple conflicts', () => {
    const datasets = [
      createMockDataset({ name: 'My Dataset' }),
      createMockDataset({ name: 'My Dataset (1)' }),
      createMockDataset({ name: 'My Dataset (2)' }),
    ];
    expect(generateUniqueDatasetName('My Dataset', datasets)).toBe('My Dataset (3)');
  });

  test('is case-insensitive', () => {
    const datasets = [createMockDataset({ name: 'MY DATASET' })];
    expect(generateUniqueDatasetName('my dataset', datasets)).toBe('my dataset (1)');
  });
});
