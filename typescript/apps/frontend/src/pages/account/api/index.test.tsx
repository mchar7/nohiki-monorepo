import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';

interface DeleteMutationOptions {
  readonly onSuccess?: () => Promise<void>;
}

const mockUseMutation = vi.hoisted(() => vi.fn());
const mockClearUserScopedPersistence = vi.hoisted(() => vi.fn());
const mockPublishAuthTransition = vi.hoisted(() => vi.fn());
const mockResetDocumentBuilderStore = vi.hoisted(() => vi.fn());
const mockResetDocumentEventStream = vi.hoisted(() => vi.fn());
const mockCancelScheduledRefresh = vi.hoisted(() => vi.fn());

vi.mock('@/features/omakase/document-builder/model/store.ts', () => ({
  resetDocumentBuilderStore: mockResetDocumentBuilderStore,
}));
vi.mock('@/entities/document/index.ts', () => ({
  resetDocumentEventStream: mockResetDocumentEventStream,
}));
vi.mock('@/shared/api/tokenRefresh.ts', () => ({
  cancelScheduledRefresh: mockCancelScheduledRefresh,
}));

vi.mock('@/shared/lib/persistence/index.ts', () => ({
  clearUserScopedPersistence: mockClearUserScopedPersistence,
}));
vi.mock('@/shared/api/auth-sync.ts', () => ({ publishAuthTransition: mockPublishAuthTransition }));

vi.mock('@/shared/api/index.ts', () => ({
  $api: {
    useMutation: mockUseMutation,
  },
}));

vi.mock('@features/account', () => ({ useAccount: vi.fn() }));

import { useAppStore } from '@/shared/model/index.ts';
import { useDeleteAccount } from './index.ts';

const originalLocation = globalThis.location;
let deleteMutationOptions: DeleteMutationOptions | undefined;
let queryClient: QueryClient;

function Wrapper({ children }: { readonly children: ReactNode }): JSX.Element {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.stubGlobal('location', { href: '' });
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  deleteMutationOptions = undefined;
  mockClearUserScopedPersistence.mockImplementation(() => {
    localStorage.removeItem('nohiki-document-builder-store');
    localStorage.removeItem('template:private');
    return Promise.resolve();
  });
  mockUseMutation.mockImplementation(
    (_method: string, _path: string, options: DeleteMutationOptions) => {
      deleteMutationOptions = options;
      return { mutate: vi.fn(), isPending: false };
    },
  );
});

afterEach(() => {
  queryClient.clear();
  localStorage.clear();
  vi.stubGlobal('location', originalLocation);
});

describe('useDeleteAccount', () => {
  test('clears account-scoped browser and query data while preserving sign-in preferences', async () => {
    localStorage.setItem('nohiki-document-builder-store', '{"datasets":[{"private":true}]}');
    localStorage.setItem('template:private', '{"name":"Private template"}');
    localStorage.setItem('nohiki:theme', 'dark');
    localStorage.setItem('i18nextLng', 'fr');
    localStorage.setItem('nohiki_remembered_email', 'user@example.com');
    queryClient.setQueryData(['account', 'private'], { email: 'user@example.com' });

    renderHook(() => useDeleteAccount(), { wrapper: Wrapper });
    const onSuccess = deleteMutationOptions?.onSuccess;
    if (!onSuccess) {
      throw new Error('Delete-account mutation did not register a success handler');
    }
    await onSuccess();

    expect(localStorage.getItem('nohiki-document-builder-store')).toBeNull();
    expect(localStorage.getItem('template:private')).toBeNull();
    expect(localStorage.getItem('nohiki:theme')).toBe('dark');
    expect(localStorage.getItem('i18nextLng')).toBe('fr');
    expect(localStorage.getItem('nohiki_remembered_email')).toBe('user@example.com');
    expect(queryClient.getQueryData(['account', 'private'])).toBeUndefined();
    expect(globalThis.location.href).toBe('/auth');
  });
  test('resets auth, pending, profile, and document state before failed cleanup can redirect', async () => {
    const cleanup = Promise.withResolvers<void>();
    mockClearUserScopedPersistence.mockReturnValue(cleanup.promise);
    useAppStore.getState().setSession({ userId: 'user-123', roles: [], permissions: [] });
    useAppStore.getState().addPendingCommand('request-1', 'generate');
    useAppStore.getState().setSelectedProfileId('profile-1');

    renderHook(() => useDeleteAccount(), { wrapper: Wrapper });
    const onSuccess = deleteMutationOptions?.onSuccess;
    if (!onSuccess) throw new Error('Delete-account mutation did not register a success handler');
    const transition = onSuccess();

    expect(useAppStore.getState().session).toBeNull();
    expect(useAppStore.getState().pendingCommands.size).toBe(0);
    expect(useAppStore.getState().selectedProfileId).toBeNull();
    expect(mockResetDocumentBuilderStore).toHaveBeenCalledTimes(1);
    expect(mockResetDocumentEventStream).toHaveBeenCalledTimes(1);
    expect(mockCancelScheduledRefresh).toHaveBeenCalledTimes(1);
    expect(globalThis.location.href).toBe('');

    cleanup.reject(new Error('IndexedDB unavailable'));
    await transition;
    expect(globalThis.location.href).toBe('/auth');
  });

  test('broadcasts deletion and completes transition when browser cleanup rejects', async () => {
    mockClearUserScopedPersistence.mockRejectedValue(new Error('IndexedDB unavailable'));
    queryClient.setQueryData(['account', 'private'], { email: 'user@example.com' });

    renderHook(() => useDeleteAccount(), { wrapper: Wrapper });
    const onSuccess = deleteMutationOptions?.onSuccess;
    if (!onSuccess) throw new Error('Delete-account mutation did not register a success handler');
    await onSuccess();

    expect(queryClient.getQueryData(['account', 'private'])).toBeUndefined();
    expect(mockPublishAuthTransition).toHaveBeenCalledWith(null);
    expect(globalThis.location.href).toBe('/auth');
  });
});
