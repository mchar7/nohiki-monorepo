import { act, renderHook } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, vi } from 'vitest';
import { ApiError } from '@/shared/api';
import type { ProfileFormValues } from '../model/index.ts';
import { useProfileCreateForm } from './useProfileCreateForm.ts';

const { mockMutateAsync, mockNavigate } = vi.hoisted(() => ({
  mockMutateAsync: vi.fn(),
  mockNavigate: vi.fn(),
}));

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../api/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/index.ts')>();
  return {
    ...actual,
    useCreateProfile: () => ({ mutateAsync: mockMutateAsync, isPending: false }),
  };
});

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const VALID_PROFILE_VALUES: ProfileFormValues = {
  pref_name: 'Backend Engineer',
  search_keywords: ['python'],
  disallowed_keywords: ['php'],
  user_skills: [],
  work_arrangements: ['REMOTE'],
  notification_threshold: 70,
  auto_tailor_threshold: null,
  open_to_relocation: false,
  salary_preference: {
    min_salary: { minor_units: 8_000_000, currency: 'USD' },
    target_salary: { minor_units: 12_000_000, currency: 'USD' },
    preferred_frequency: 'ANNUALLY',
  },
  experience_preference: {
    experience_years: 5,
    seniority_levels: ['SENIOR'],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  mockNavigate.mockResolvedValue(undefined);
});

describe('useProfileCreateForm', () => {
  test('keeps a 422 response as a form failure instead of navigating', async () => {
    mockMutateAsync.mockRejectedValue(new ApiError('Profile validation failed', 422));

    const { result } = renderHook(() => {
      const profileForm = useProfileCreateForm();
      void profileForm.form.formState.errors;
      return profileForm;
    });

    await act(async () => {
      await result.current.onSubmit(VALID_PROFILE_VALUES);
    });

    expect(mockMutateAsync).toHaveBeenCalledWith({
      body: expect.objectContaining({
        pref_name: 'Backend Engineer',
        search_keywords: ['python'],
        disallowed_keywords: ['php'],
      }),
    });
    expect(result.current.form.formState.errors.root?.message).toContain(
      'Profile validation failed',
    );
    expect(toast.error).toHaveBeenCalledTimes(1);
    expect(toast.success).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
