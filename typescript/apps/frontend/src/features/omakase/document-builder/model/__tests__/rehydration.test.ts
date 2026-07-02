import { describe, expect } from 'vitest';
import { rebuildIndex } from '../slices/datasetSlice.ts';
import type { Dataset } from '../types.ts';

describe('rebuildIndex', () => {
  test('rebuilds dataset index from array', () => {
    const datasets: Dataset[] = [
      {
        id: 'ds-1',
        name: 'Resume A',
        templateVersionId: 'tmpl-1',
        data: {},
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
      {
        id: 'ds-2',
        name: 'Resume B',
        templateVersionId: 'tmpl-1',
        data: {},
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    ];

    const index = rebuildIndex(datasets);

    expect(index).toBeInstanceOf(Map);
    expect(index.size).toBe(2);
    expect(index.get('ds-1')).toBe(datasets[0]);
    expect(index.get('ds-2')).toBe(datasets[1]);
    expect(index.get('nonexistent')).toBeUndefined();
  });

  test('returns empty Map for empty array', () => {
    const index = rebuildIndex([]);

    expect(index).toBeInstanceOf(Map);
    expect(index.size).toBe(0);
  });

  test('handles single dataset', () => {
    const dataset: Dataset = {
      id: 'ds-only',
      name: 'Only Dataset',
      templateVersionId: 'tmpl-1',
      data: {},
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    const index = rebuildIndex([dataset]);

    expect(index.size).toBe(1);
    expect(index.get('ds-only')).toBe(dataset);
  });
});
