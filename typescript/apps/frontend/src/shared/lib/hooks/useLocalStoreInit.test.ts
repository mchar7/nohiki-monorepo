import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useLocalStoreInit, useStoresReady } from './useLocalStoreInit.ts';

vi.mock('@/shared/model/local/datasetStore', () => ({
  useDatasetStore: vi.fn((selector) => {
    const state = {
      initialize: vi.fn().mockResolvedValue(undefined),
      isInitialized: false,
      isLoading: false,
    };
    return selector(state);
  }),
}));

vi.mock('@/shared/model/local/schemaStore', () => ({
  useSchemaStore: vi.fn((selector) => {
    const state = {
      initialize: vi.fn().mockResolvedValue(undefined),
      isInitialized: false,
      isLoading: false,
    };
    return selector(state);
  }),
}));

vi.mock('@/shared/model/local/templateStore', () => ({
  useTemplateStore: vi.fn((selector) => {
    const state = {
      initialize: vi.fn().mockResolvedValue(undefined),
      isInitialized: false,
      isLoading: false,
    };
    return selector(state);
  }),
}));

describe('useLocalStoreInit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('useLocalStoreInit', () => {
    test('returns initial state', () => {
      const { result } = renderHook(() => useLocalStoreInit());

      expect(result.current).toMatchObject({
        isInitializing: expect.any(Boolean),
        isInitialized: expect.any(Boolean),
        error: null,
      });
    });

    test('initializes stores', async () => {
      const { result } = renderHook(() => useLocalStoreInit());

      await waitFor(() => {
        expect(result.current.isInitializing || result.current.isInitialized).toBe(true);
      });
    });
  });

  describe('useStoresReady', () => {
    test('returns false when stores are not ready', () => {
      const { result } = renderHook(() => useStoresReady());

      expect(result.current).toBe(false);
    });
  });
});
