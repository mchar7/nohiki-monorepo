import { useQueryClient } from '@tanstack/react-query';
import { resetDocumentEventStream } from '@/entities/document/index.ts';
import { resetDocumentBuilderStore } from '@/features/omakase/document-builder/model/store.ts';
import type { UserResponse } from '@/shared/api';
import { publishAuthTransition } from '@/shared/api/auth-sync.ts';
import { $api } from '@/shared/api/index.ts';
import { cancelScheduledRefresh } from '@/shared/api/tokenRefresh.ts';
import { clearUserScopedPersistence } from '@/shared/lib/persistence/index.ts';
import { logger } from '@/shared/lib/utils/logger.ts';
import { useAppStore } from '@/shared/model/index.ts';

export { useAccount } from '@features/account';

export function useUpdateAccount() {
  const queryClient = useQueryClient();
  return $api.useMutation('patch', '/api/v1/account', {
    onSuccess: (data: UserResponse) => {
      const accountKey = $api.queryOptions('get', '/api/v1/account').queryKey;
      queryClient.setQueryData<UserResponse>(accountKey, data);
    },
  });
}

export function useDeleteAccount() {
  const queryClient = useQueryClient();
  return $api.useMutation('delete', '/api/v1/account', {
    onSuccess: async () => {
      const appStore = useAppStore.getState();
      appStore.logout();
      appStore.clearPendingCommands();
      appStore.setSelectedProfileId(null);
      resetDocumentBuilderStore();
      resetDocumentEventStream();
      cancelScheduledRefresh();
      queryClient.clear();

      try {
        await clearUserScopedPersistence();
      } catch (error) {
        logger.error('Failed to clear user-scoped persistence after account deletion', error);
      }
      publishAuthTransition(null);
      globalThis.location.href = '/auth';
    },
  });
}

export function useOAuthIdentities() {
  return $api.useQuery('get', '/api/v1/account/oauth-identities');
}

export function useOAuthProviders() {
  return $api.useQuery('get', '/api/v1/auth/oauth/providers');
}

export function useUnlinkOAuth() {
  const queryClient = useQueryClient();

  return $api.useMutation('delete', '/api/v1/account/oauth/{provider}', {
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: $api.queryOptions('get', '/api/v1/account/oauth-identities').queryKey,
      });
    },
  });
}
