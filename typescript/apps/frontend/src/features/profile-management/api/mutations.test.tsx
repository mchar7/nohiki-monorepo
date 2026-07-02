import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type {
  CommandAcceptedResponse,
  FeatureImportanceRequest,
  ProfileCreate,
  ProfileUpdate,
} from '@/shared/api';
import {
  useAssociateAttachment,
  useCreateProfile,
  useDeleteProfile,
  useDisassociateAttachment,
  useSetDefaultFeatureImportance,
  useSetFeatureImportance,
  useUpdateProfile,
} from './index.ts';

const {
  mockPost,
  mockPatch,
  mockDelete,
  mockPut,
}: {
  mockPost: ReturnType<typeof vi.fn>;
  mockPatch: ReturnType<typeof vi.fn>;
  mockDelete: ReturnType<typeof vi.fn>;
  mockPut: ReturnType<typeof vi.fn>;
} = vi.hoisted(() => ({
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
  mockPut: vi.fn(),
}));

vi.mock('@/shared/api/client', async () => {
  const { default: createQueryClient } =
    await vi.importActual<typeof import('openapi-react-query')>('openapi-react-query');
  const client = {
    GET: vi.fn(),
    POST: mockPost,
    DELETE: mockDelete,
    PATCH: mockPatch,
    PUT: mockPut,
  };
  return {
    fetchClient: client,
    $api: createQueryClient(client as never),
    createDevClient: vi.fn(),
  };
});

/** Creates a mock response matching openapi-fetch's return shape (data + error + response). */
function mockFetchResponse(data: unknown): {
  data: unknown;
  error: undefined;
  response: { status: number; headers: Headers };
} {
  return {
    data,
    error: undefined,
    response: { status: 200, headers: new Headers({ 'Content-Length': '1' }) },
  };
}

function createWrapper(): ({ children }: { children: ReactNode }) => JSX.Element {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('useCreateProfile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls create profile API and returns CommandAcceptedResponse', async () => {
    const createPayload: ProfileCreate = {
      pref_name: 'New Profile',
      search_keywords: ['python', 'fastapi'],
      notification_threshold: 0.7,
      open_to_relocation: false,
      work_arrangements: ['REMOTE'],
      salary_preference: {
        min_salary: { minor_units: 8_000_000, currency: 'USD' as const },
        target_salary: { minor_units: 12_000_000, currency: 'USD' as const },
        preferred_frequency: 'ANNUALLY',
      },
      experience_preference: {
        experience_years: 5,
        seniority_levels: ['SENIOR'],
      },
    };
    const mockResponse: CommandAcceptedResponse = {
      request_id: 'req-abc-123',
      status: 'accepted',
    };
    mockPost.mockResolvedValue(mockFetchResponse(mockResponse));

    const { result } = renderHook(() => useCreateProfile(), { wrapper: createWrapper() });

    const response = await result.current.mutateAsync({ body: createPayload });

    expect(response).toEqual(mockResponse);
    expect(mockPost).toHaveBeenCalledWith(
      '/api/v1/profiles',
      expect.objectContaining({ body: createPayload }),
    );
  });
});

describe('useUpdateProfile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls update profile API with correct field names', async () => {
    const mockResponse: CommandAcceptedResponse = {
      request_id: 'req-update-123',
      status: 'accepted',
    };
    mockPatch.mockResolvedValue(mockFetchResponse(mockResponse));

    const updateData: ProfileUpdate = { pref_name: 'Updated Name' };
    const { result } = renderHook(() => useUpdateProfile(), { wrapper: createWrapper() });

    await result.current.mutateAsync({
      params: { path: { pref_id: 'prof-123' } },
      body: updateData,
    });

    expect(mockPatch).toHaveBeenCalledWith(
      '/api/v1/profiles/{pref_id}',
      expect.objectContaining({
        params: { path: { pref_id: 'prof-123' } },
        body: updateData,
      }),
    );
  });
});

describe('useDeleteProfile', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls delete profile API', async () => {
    const mockResponse: CommandAcceptedResponse = {
      request_id: 'req-delete-123',
      status: 'accepted',
    };
    mockDelete.mockResolvedValue(mockFetchResponse(mockResponse));

    const { result } = renderHook(() => useDeleteProfile(), { wrapper: createWrapper() });

    await result.current.mutateAsync({ params: { path: { pref_id: 'prof-123' } } });

    expect(mockDelete).toHaveBeenCalledWith(
      '/api/v1/profiles/{pref_id}',
      expect.objectContaining({
        params: { path: { pref_id: 'prof-123' } },
      }),
    );
  });
});

describe('useSetFeatureImportance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls set feature importance API with correct field names', async () => {
    const mockResponse: CommandAcceptedResponse = {
      request_id: 'req-fi-123',
      status: 'accepted',
    };
    mockPut.mockResolvedValue(mockFetchResponse(mockResponse));

    const importanceData: FeatureImportanceRequest = { salary_importance: 90 };
    const { result } = renderHook(() => useSetFeatureImportance(), { wrapper: createWrapper() });

    await result.current.mutateAsync({
      params: { path: { pref_id: 'prof-123' } },
      body: importanceData,
    });

    expect(mockPut).toHaveBeenCalledWith(
      '/api/v1/profiles/{pref_id}/feature-importance',
      expect.objectContaining({
        params: { path: { pref_id: 'prof-123' } },
        body: importanceData,
      }),
    );
  });
});

describe('useSetDefaultFeatureImportance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls set default feature importance API with correct field names', async () => {
    const mockResponse: CommandAcceptedResponse = {
      request_id: 'req-dfi-123',
      status: 'accepted',
    };
    mockPut.mockResolvedValue(mockFetchResponse(mockResponse));

    const importanceData: FeatureImportanceRequest = { salary_importance: 70 };
    const { result } = renderHook(() => useSetDefaultFeatureImportance(), {
      wrapper: createWrapper(),
    });

    await result.current.mutateAsync({ body: importanceData });

    expect(mockPut).toHaveBeenCalledWith(
      '/api/v1/profiles/settings/feature-importance',
      expect.objectContaining({
        body: importanceData,
      }),
    );
  });
});

describe('useAssociateAttachment', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls associate attachment API', async () => {
    const mockResponse: CommandAcceptedResponse = {
      request_id: 'req-assoc-123',
      status: 'accepted',
    };
    mockPost.mockResolvedValue(mockFetchResponse(mockResponse));

    const { result } = renderHook(() => useAssociateAttachment(), { wrapper: createWrapper() });

    await result.current.mutateAsync({
      params: { path: { pref_id: 'prof-123', upload_id: 'upload-456' } },
    });

    expect(mockPost).toHaveBeenCalledWith(
      '/api/v1/profiles/{pref_id}/attachments/{upload_id}',
      expect.objectContaining({
        params: { path: { pref_id: 'prof-123', upload_id: 'upload-456' } },
      }),
    );
  });
});

describe('useDisassociateAttachment', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('calls disassociate attachment API', async () => {
    const mockResponse: CommandAcceptedResponse = {
      request_id: 'req-disassoc-123',
      status: 'accepted',
    };
    mockDelete.mockResolvedValue(mockFetchResponse(mockResponse));

    const { result } = renderHook(() => useDisassociateAttachment(), { wrapper: createWrapper() });

    await result.current.mutateAsync({
      params: { path: { pref_id: 'prof-123', upload_id: 'upload-456' } },
    });

    expect(mockDelete).toHaveBeenCalledWith(
      '/api/v1/profiles/{pref_id}/attachments/{upload_id}',
      expect.objectContaining({
        params: { path: { pref_id: 'prof-123', upload_id: 'upload-456' } },
      }),
    );
  });
});
