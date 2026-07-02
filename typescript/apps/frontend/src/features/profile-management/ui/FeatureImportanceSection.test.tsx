import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import type { Mock } from 'vitest';
import { afterEach, describe, expect, vi } from 'vitest';

// Mock the feature-management API hooks
vi.mock('../api/index.ts', () => ({
  useResolvedFeatureImportance: vi.fn(),
  useSetFeatureImportance: vi.fn(),
}));

// Mock useFormAutoSave to control when saves fire
vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return { ...actual, useFormAutoSave: vi.fn() };
});

import { useFormAutoSave } from '@/shared/lib/index.ts';
import { useResolvedFeatureImportance, useSetFeatureImportance } from '../api/index.ts';
import { FeatureImportanceSection } from './FeatureImportanceSection.tsx';

const mockUseResolvedFeatureImportance = useResolvedFeatureImportance as Mock;
const mockUseSetFeatureImportance = useSetFeatureImportance as Mock;
const mockUseFormAutoSave = useFormAutoSave as Mock;

const MOCK_IMPORTANCE = {
  source: 'user_default' as const,
  skill_match_importance: 80,
  location_importance: 50,
  work_arrangement_importance: 70,
  experience_importance: 60,
  salary_importance: 90,
  recency_importance: 40,
};

function createWrapper(): ({ children }: { children: ReactNode }) => JSX.Element {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('FeatureImportanceSection', () => {
  test('returns null while loading', () => {
    mockUseResolvedFeatureImportance.mockReturnValue({ data: undefined, isLoading: true });
    mockUseSetFeatureImportance.mockReturnValue({ mutate: vi.fn() });
    mockUseFormAutoSave.mockReturnValue(undefined);

    const { container } = render(<FeatureImportanceSection profileId="prof-1" />, {
      wrapper: createWrapper(),
    });
    expect(container.firstChild).toBeNull();
    expect(mockUseFormAutoSave).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.any(Object),
        isDirty: expect.any(Boolean),
        onSave: expect.any(Function),
        debounceMs: 500,
      }),
    );
  });

  test('renders server integer values as percentages without scaling them', () => {
    mockUseResolvedFeatureImportance.mockReturnValue({ data: MOCK_IMPORTANCE, isLoading: false });
    mockUseSetFeatureImportance.mockReturnValue({ mutate: vi.fn() });
    mockUseFormAutoSave.mockReturnValue(undefined);

    render(<FeatureImportanceSection profileId="prof-1" />, { wrapper: createWrapper() });

    expect(screen.getAllByText('80%')).toHaveLength(1);
    expect(screen.queryByText('8000%')).toBeNull();
  });

  test('autosaves the exact integer feature importance payload', () => {
    const mutate = vi.fn();
    mockUseResolvedFeatureImportance.mockReturnValue({ data: MOCK_IMPORTANCE, isLoading: false });
    mockUseSetFeatureImportance.mockReturnValue({ mutate });
    mockUseFormAutoSave.mockReturnValue(undefined);

    render(<FeatureImportanceSection profileId="prof-1" />, { wrapper: createWrapper() });
    const { onSave } = mockUseFormAutoSave.mock.calls.at(-1)[0];
    const values = {
      skill_match_importance: 80,
      location_importance: 50,
      work_arrangement_importance: 70,
      experience_importance: 60,
      salary_importance: 90,
      recency_importance: 40,
    };

    onSave(values);
    expect(mutate).toHaveBeenCalledWith({ params: { path: { pref_id: 'prof-1' } }, body: values });
  });

  test('renders FeatureImportanceSettings when data is loaded', () => {
    mockUseResolvedFeatureImportance.mockReturnValue({ data: MOCK_IMPORTANCE, isLoading: false });
    mockUseSetFeatureImportance.mockReturnValue({ mutate: vi.fn() });
    mockUseFormAutoSave.mockReturnValue(undefined);

    const { container } = render(<FeatureImportanceSection profileId="prof-1" />, {
      wrapper: createWrapper(),
    });
    // FeatureImportanceSettings renders content; verify it mounts without crash
    expect(container.firstChild).not.toBeNull();
    expect(mockUseFormAutoSave).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.any(Object),
        isDirty: expect.any(Boolean),
        onSave: expect.any(Function),
        debounceMs: 500,
      }),
    );
  });

  test('passes profileId to useResolvedFeatureImportance', () => {
    mockUseResolvedFeatureImportance.mockReturnValue({ data: undefined, isLoading: true });
    mockUseSetFeatureImportance.mockReturnValue({ mutate: vi.fn() });
    mockUseFormAutoSave.mockReturnValue(undefined);

    render(<FeatureImportanceSection profileId="prof-42" />, { wrapper: createWrapper() });
    expect(mockUseResolvedFeatureImportance).toHaveBeenCalledWith('prof-42');
    expect(mockUseFormAutoSave).toHaveBeenCalled();
  });
});

describe('FeatureImportanceSection hooks', () => {
  test('calls useSetFeatureImportance hook', () => {
    mockUseResolvedFeatureImportance.mockReturnValue({ data: undefined, isLoading: false });
    mockUseSetFeatureImportance.mockReturnValue({ mutate: vi.fn() });
    mockUseFormAutoSave.mockReturnValue(undefined);

    render(<FeatureImportanceSection profileId="prof-1" />, { wrapper: createWrapper() });
    expect(mockUseSetFeatureImportance).toHaveBeenCalled();
    expect(mockUseFormAutoSave).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.any(Object),
        isDirty: expect.any(Boolean),
        onSave: expect.any(Function),
        debounceMs: 500,
      }),
    );
  });
});
