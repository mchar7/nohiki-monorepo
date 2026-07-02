import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useTemplateLoader } from './useTemplateLoader.ts';

const { mockUseTemplateFamilies } = vi.hoisted(() => ({
  mockUseTemplateFamilies: vi.fn(),
}));

const mockRefetch = vi.fn();
const mockSetTemplateFamilies = vi.fn();
const mockSetSelectedFamily = vi.fn();

const mockState = {
  templateFamilies: [],
  selectedFamilyId: null as string | null,
  setTemplateFamilies: mockSetTemplateFamilies,
  setSelectedFamily: mockSetSelectedFamily,
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => `translated:${key}` }),
}));

vi.mock('@/shared/lib/contexts/index.ts', () => ({
  useConnectivitySafe: () => ({ isOffline: false, hasChecked: true }),
}));

vi.mock('../api/hooks.ts', () => ({
  useTemplateFamilies: (...args: unknown[]) => mockUseTemplateFamilies(...args),
}));

vi.mock('../model/index.ts', () => ({
  useDocumentBuilderStore: (selector: (state: typeof mockState) => unknown) => selector(mockState),
}));

describe('useTemplateLoader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.templateFamilies = [];
    mockState.selectedFamilyId = null;
  });

  test('hydrates template families and selects the first family when none is selected', async () => {
    const items = [{ id: 'family-1' }, { id: 'family-2' }];
    mockUseTemplateFamilies.mockReturnValue({
      data: { items },
      isLoading: false,
      error: null,
      refetch: mockRefetch,
    });

    const { result } = renderHook(() => useTemplateLoader());

    await waitFor(() => {
      expect(mockSetTemplateFamilies).toHaveBeenCalledWith(items);
      expect(mockSetSelectedFamily).toHaveBeenCalledWith('family-1');
    });

    expect(result.current.templateFamilies).toBe(mockState.templateFamilies);
    expect(result.current.selectedFamilyId).toBeNull();
    expect(result.current.reloadTemplates).toBe(mockRefetch);
    expect(result.current.isConfirmedOffline).toBe(false);
  });

  test('maps API errors to a translated user-facing message', () => {
    mockUseTemplateFamilies.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('401 Unauthorized'),
      refetch: mockRefetch,
    });

    const { result } = renderHook(() => useTemplateLoader());

    expect(result.current.error).toBe('translated:templates.errors.authRequired');
  });
});
