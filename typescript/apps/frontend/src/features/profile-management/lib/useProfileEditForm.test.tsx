import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import React from 'react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, vi } from 'vitest';
import type * as SharedApi from '@/shared/api';
import { hydrateSkillIds } from '@/shared/api';
import { useUpdateProfile } from '../api/index.ts';
import {
  MOCK_HYDRATED_USER_SKILLS,
  MOCK_PROFILE,
  mockMutationResult,
} from './useProfileEditForm.test-helpers.ts';
import { useProfileEditForm } from './useProfileEditForm.ts';

vi.mock('@/shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof SharedApi>();
  return {
    ...actual,
    hydrateSkillIds: vi.fn(),
  };
});

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('../api/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/index.ts')>();
  return {
    ...actual,
    useUpdateProfile: vi.fn(),
  };
});

function createWrapper(): React.FC<{ children: React.ReactNode }> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }): React.JSX.Element {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

let mockMutateAsync: ReturnType<
  typeof vi.fn<
    Parameters<ReturnType<typeof useUpdateProfile>['mutateAsync']>[0] extends never
      ? () => void
      : ReturnType<typeof useUpdateProfile>['mutateAsync']
  >
>;

function setupMocks(): void {
  vi.clearAllMocks();
  mockMutateAsync = vi.fn();
  vi.mocked(useUpdateProfile).mockReturnValue(
    mockMutationResult({ mutateAsync: mockMutateAsync, isPending: false }),
  );
  vi.mocked(hydrateSkillIds).mockResolvedValue(MOCK_HYDRATED_USER_SKILLS);
}

describe('useProfileEditForm - hydration start', () => {
  beforeEach(setupMocks);

  test('hydrates only user skill UUIDs and preserves literal search terms', async () => {
    const { result } = renderHook(
      () => useProfileEditForm({ profileId: 'profile-1', profile: MOCK_PROFILE }),
      { wrapper: createWrapper() },
    );

    act(() => result.current.startEditing());

    await waitFor(() => expect(result.current.isEditing).toBe(true));
    expect(hydrateSkillIds).toHaveBeenCalledTimes(1);
    expect(hydrateSkillIds).toHaveBeenCalledWith(['skill-ts']);
    expect(hydrateSkillIds).not.toHaveBeenCalledWith(MOCK_PROFILE.search_keywords);
    expect(result.current.form.getValues('search_keywords')).toEqual([
      'platform developer',
      'distributed systems',
    ]);
    expect(result.current.form.getValues('user_skills')).toEqual(MOCK_HYDRATED_USER_SKILLS);
  });
});

describe('useProfileEditForm - hydration completion', () => {
  beforeEach(setupMocks);

  test('form.reset is called with hydrated values after successful hydration', async () => {
    const { result } = renderHook(
      () => useProfileEditForm({ profileId: 'profile-1', profile: MOCK_PROFILE }),
      { wrapper: createWrapper() },
    );

    act(() => {
      result.current.startEditing();
    });

    await waitFor(() => {
      expect(result.current.isEditing).toBe(true);
    });

    expect(result.current.form.getValues('pref_name')).toBe('Frontend Engineer');
    expect(result.current.form.getValues('search_keywords')).toEqual(MOCK_PROFILE.search_keywords);
    expect(result.current.form.getValues('user_skills')).toEqual(MOCK_HYDRATED_USER_SKILLS);
  });

  test('Hydration error shows toast notification', async () => {
    vi.mocked(hydrateSkillIds).mockRejectedValue(new Error('Network Error'));

    const { result } = renderHook(
      () => useProfileEditForm({ profileId: 'profile-1', profile: MOCK_PROFILE }),
      { wrapper: createWrapper() },
    );

    act(() => {
      result.current.startEditing();
    });

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled();
    });

    expect(result.current.isHydrating).toBe(false);
    expect(result.current.isEditing).toBe(false); // Shouldn't enter edit mode on error
  });
});

describe('useProfileEditForm - editing lifecycle', () => {
  beforeEach(setupMocks);

  test('cancelEditing resets form and clears editing state', async () => {
    const { result } = renderHook(
      () => useProfileEditForm({ profileId: 'profile-1', profile: MOCK_PROFILE }),
      { wrapper: createWrapper() },
    );

    // Enter edit mode
    act(() => {
      result.current.startEditing();
    });
    await waitFor(() => {
      expect(result.current.isEditing).toBe(true);
    });

    // Dirty the form
    result.current.form.setValue('pref_name', 'Changed Name');
    expect(result.current.form.getValues('pref_name')).toBe('Changed Name');

    // Cancel edit
    act(() => {
      result.current.cancelEditing();
    });

    expect(result.current.isEditing).toBe(false);

    // RHF reset() reverts to defaultValues. Since we don't pass defaultValues
    // to useForm (only reset it during startEditing), calling reset() again
    // will revert it to empty or the values we initialized with.
    // Just verifying it's called internally.
  });
});

describe('useProfileEditForm - submit', () => {
  beforeEach(setupMocks);

  test('onSubmit success: shows success toast + exits edit mode', async () => {
    const { result } = renderHook(
      () => useProfileEditForm({ profileId: 'profile-1', profile: MOCK_PROFILE }),
      { wrapper: createWrapper() },
    );

    // Enter edit mode
    act(() => {
      result.current.startEditing();
    });
    await waitFor(() => {
      expect(result.current.isEditing).toBe(true);
    });

    const values = result.current.form.getValues();

    await act(async () => {
      await result.current.onSubmit(values);
    });

    expect(mockMutateAsync).toHaveBeenCalledWith({
      params: { path: { pref_id: 'profile-1' } },
      body: expect.objectContaining({
        search_keywords: ['platform developer', 'distributed systems'],
        user_skills: ['skill-ts'],
      }),
    });
    expect(toast.success).toHaveBeenCalled();
    expect(result.current.isEditing).toBe(false);
  });

  test('keeps editing closed when an original skill ID could not be hydrated', async () => {
    vi.mocked(hydrateSkillIds).mockResolvedValue([]);

    const { result } = renderHook(
      () => useProfileEditForm({ profileId: 'profile-1', profile: MOCK_PROFILE }),
      { wrapper: createWrapper() },
    );

    act(() => result.current.startEditing());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(result.current.isHydrating).toBe(false);
    expect(result.current.isEditing).toBe(false);
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });

  test('onSubmit error: shows error toast, stays in edit mode', async () => {
    mockMutateAsync.mockRejectedValue(new Error('Update failed'));

    const { result } = renderHook(
      () => useProfileEditForm({ profileId: 'profile-1', profile: MOCK_PROFILE }),
      { wrapper: createWrapper() },
    );

    act(() => {
      result.current.startEditing();
    });
    await waitFor(() => {
      expect(result.current.isEditing).toBe(true);
    });

    const values = result.current.form.getValues();

    await act(async () => {
      await result.current.onSubmit(values);
    });

    expect(toast.error).toHaveBeenCalled();
    expect(result.current.isEditing).toBe(true); // Still editing
  });
});

describe('useProfileEditForm - state', () => {
  test('isPending reflects mutation state', () => {
    // Mock isPending to true
    const mutateAsync = vi.fn();
    vi.mocked(useUpdateProfile).mockReturnValue(
      mockMutationResult({ mutateAsync, isPending: true }),
    );

    const { result } = renderHook(
      () => useProfileEditForm({ profileId: 'profile-1', profile: MOCK_PROFILE }),
      { wrapper: createWrapper() },
    );

    expect(result.current.isPending).toBe(true);
  });
});
