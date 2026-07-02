import { useNavigate } from '@tanstack/react-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { extractErrorReason } from '@/shared/lib/index.ts';
import { useDeleteProfile } from '../api/index.ts';

interface UseProfileDeleteOptions {
  profileId: string;
}

interface UseProfileDeleteResult {
  showDialog: boolean;
  openDialog: () => void;
  closeDialog: () => void;
  confirmDelete: () => Promise<void>;
  isPending: boolean;
}

/**
 * Hook encapsulating profile deletion logic with confirmation dialog state.
 * Separates business logic from UI presentation.
 */
export function useProfileDelete({ profileId }: UseProfileDeleteOptions): UseProfileDeleteResult {
  const { t } = useTranslation(['profiles', 'common']);
  const navigate = useNavigate();
  const deleteMutation = useDeleteProfile();
  const [showDialog, setShowDialog] = useState(false);

  const openDialog = (): void => setShowDialog(true);
  const closeDialog = (): void => setShowDialog(false);

  const confirmDelete = async (): Promise<void> => {
    try {
      await deleteMutation.mutateAsync({ params: { path: { pref_id: profileId } } });
      toast.success(t('profiles:pages.detail.deleteSuccess'));
      navigate({ to: ROUTE_PATHS.PROFILES.LIST });
    } catch (error: unknown) {
      const reason = extractErrorReason(error);
      toast.error(
        reason
          ? t('profiles:pages.detail.deleteError', { reason })
          : t('profiles:pages.detail.deleteErrorFallback'),
      );
    }
  };

  return {
    showDialog,
    openDialog,
    closeDialog,
    confirmDelete,
    isPending: deleteMutation.isPending,
  };
}
