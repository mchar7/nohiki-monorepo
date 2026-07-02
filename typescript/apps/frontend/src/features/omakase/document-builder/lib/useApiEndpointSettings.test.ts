import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { useApiEndpointSettings } from './useApiEndpointSettings.ts';

vi.mock('@/shared/api/client', () => ({
  fetchClient: { GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn(), PATCH: vi.fn(), PUT: vi.fn() },
  $api: { useQuery: vi.fn(), useMutation: vi.fn() },
  createDevClient: vi.fn(),
}));

const TRAILING_SLASHES_RE = /\/+$/u;
const API_SUFFIX_RE = /\/api$/u;

vi.mock('./useApiEndpointHealthCheck', () => ({
  normalizeEndpoint: (url: string) =>
    url.replace(TRAILING_SLASHES_RE, '').replace(API_SUFFIX_RE, ''),
}));

const mockLocalStorage: {
  getItem: ReturnType<typeof vi.fn>;
  setItem: ReturnType<typeof vi.fn>;
  removeItem: ReturnType<typeof vi.fn>;
} = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
};

beforeEach(() => {
  vi.stubGlobal('localStorage', mockLocalStorage);
  vi.stubEnv('DEV', true);
  mockLocalStorage.getItem.mockReturnValue(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe('useApiEndpointSettings - initialization', () => {
  test('returns default endpoint initially', () => {
    const { result } = renderHook(() => useApiEndpointSettings());

    expect(result.current.endpoint).toBe('http://localhost:8000');
    expect(result.current.isCustomEndpoint).toBe(false);
  });

  test('loads stored endpoint from localStorage', () => {
    mockLocalStorage.getItem.mockReturnValue('http://custom:9000');

    const { result } = renderHook(() => useApiEndpointSettings());

    expect(result.current.endpoint).toBe('http://custom:9000');
    expect(result.current.isCustomEndpoint).toBe(true);
  });

  test('handles localStorage errors gracefully', () => {
    mockLocalStorage.getItem.mockImplementation(() => {
      throw new Error('Storage error');
    });

    const { result } = renderHook(() => useApiEndpointSettings());

    expect(result.current.endpoint).toBe('http://localhost:8000');
  });
});

describe('useApiEndpointSettings - mutations', () => {
  test('setEndpoint updates endpoint and saves to localStorage', () => {
    const { result } = renderHook(() => useApiEndpointSettings());

    act(() => {
      result.current.setEndpoint('http://new-endpoint:8080');
    });

    expect(result.current.endpoint).toBe('http://new-endpoint:8080');
    expect(mockLocalStorage.setItem).toHaveBeenCalledWith(
      'dev-api-endpoint',
      'http://new-endpoint:8080',
    );
  });

  test('resetToDefault restores default endpoint', () => {
    mockLocalStorage.getItem.mockReturnValue('http://custom:9000');

    const { result } = renderHook(() => useApiEndpointSettings());

    act(() => {
      result.current.resetToDefault();
    });

    expect(result.current.endpoint).toBe('http://localhost:8000');
    expect(result.current.isCustomEndpoint).toBe(false);
    expect(mockLocalStorage.removeItem).toHaveBeenCalledWith('dev-api-endpoint');
  });

  test('saveEndpoint normalizes and saves endpoint', () => {
    const { result } = renderHook(() => useApiEndpointSettings());

    act(() => {
      result.current.saveEndpoint('http://example.com/api/');
    });

    expect(result.current.endpoint).toBe('http://example.com');
  });
});
