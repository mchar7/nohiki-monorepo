import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateFamilyResponse } from '@/shared/api';
import { HTTP_STATUS } from '@/shared/config/index.ts';
import { useConnectivitySafe } from '@/shared/lib/contexts/index.ts';
import { useTemplateFamilies } from '../api/hooks.ts';
import { useDocumentBuilderStore } from '../model/index.ts';

type ErrorKey =
  | 'templates.errors.authRequired'
  | 'templates.errors.forbidden'
  | 'templates.errors.networkError'
  | 'templates.errors.serverError'
  | 'templates.errors.timeout'
  | 'templates.errors.notFound'
  | 'templates.errors.generic';

function extractErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function extractErrorStatus(error: unknown): number | null {
  if (error && typeof error === 'object' && 'status' in error) {
    return (error as { status: number }).status;
  }
  return null;
}

function categorizeError(error: unknown): ErrorKey {
  const errorMessage = extractErrorMessage(error);
  const errorStatus = extractErrorStatus(error);

  if (
    errorStatus === HTTP_STATUS.UNAUTHORIZED ||
    errorMessage.includes('401') ||
    errorMessage.includes('Unauthorized')
  ) {
    return 'templates.errors.authRequired';
  }
  if (
    errorStatus === HTTP_STATUS.FORBIDDEN ||
    errorMessage.includes('403') ||
    errorMessage.includes('Forbidden')
  ) {
    return 'templates.errors.forbidden';
  }
  if (errorMessage.includes('NetworkError') || errorMessage.includes('fetch')) {
    return 'templates.errors.networkError';
  }
  if (errorMessage.includes('500') || errorMessage.includes('Internal Server')) {
    return 'templates.errors.serverError';
  }
  if (errorMessage.includes('timeout') || errorMessage.includes('Timeout')) {
    return 'templates.errors.timeout';
  }
  if (errorMessage.includes('404')) {
    return 'templates.errors.notFound';
  }
  return 'templates.errors.generic';
}

export function useTemplateLoader(): {
  isLoading: boolean;
  error: string | null;
  isLoaded: boolean;
  templateFamilies: TemplateFamilyResponse[];
  selectedFamilyId: string | null;
  reloadTemplates: () => void;
  isConfirmedOffline: boolean;
} {
  const { t } = useTranslation('omakase.editor');
  const { isOffline, hasChecked } = useConnectivitySafe();

  // Don't fetch if we've confirmed we're offline
  const isConfirmedOffline = hasChecked && isOffline;

  const { data, isLoading, error, refetch } = useTemplateFamilies();

  const templateFamilies = useDocumentBuilderStore((state) => state.templateFamilies);
  const selectedFamilyId = useDocumentBuilderStore((state) => state.selectedFamilyId);
  const setTemplateFamilies = useDocumentBuilderStore((state) => state.setTemplateFamilies);
  const setSelectedFamily = useDocumentBuilderStore((state) => state.setSelectedFamily);

  useEffect(() => {
    if (data?.items) {
      setTemplateFamilies(data.items);

      const [firstItem] = data.items;
      if (!selectedFamilyId && firstItem) {
        setSelectedFamily(firstItem.id);
      }
    }
  }, [data, selectedFamilyId, setTemplateFamilies, setSelectedFamily]);

  const getUserFriendlyError = (): string | null => {
    if (!error) {
      return null;
    }
    return t(categorizeError(error));
  };

  return {
    // Don't show loading if we know we're offline
    isLoading: isLoading && !isConfirmedOffline,
    error: getUserFriendlyError(),
    isLoaded: Boolean(data),
    templateFamilies,
    selectedFamilyId,
    reloadTemplates: refetch,
    isConfirmedOffline,
  };
}
