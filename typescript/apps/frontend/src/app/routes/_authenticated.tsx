import {
  type AnyRoute,
  createFileRoute,
  type ParsedLocation,
  redirect,
  useRouter,
} from '@tanstack/react-router';

/** Delay before eagerly prefetching authenticated routes on mount (ms) */
const PREFETCH_DELAY_MS: number = 2000;

import type { JSX } from 'react';
import { useEffect } from 'react';
import type { RouterContext } from '@/app/router-context.ts';
import { AuthProvider } from '@/features/auth/index.ts';
import { ApiError, authApi, CACHE_CONFIG, queryKeys } from '@/shared/api/index.ts';
import { HTTP_STATUS } from '@/shared/config/index.ts';
import { handleNavigationPromise } from '@/shared/lib/index.ts';
import { PageLoading } from '@/shared/ui/page-loading.tsx';
import { BaseLayout } from '@/widgets/layout/index.ts';

const GREEDY_PREFETCH_ROUTES = [
  { to: '/jobs' },
  { to: '/jobs/matches' },
  { to: '/profiles' },
  { to: '/account' },
  { to: '/documents' },
  { to: '/settings' },
] as const;

const Route: AnyRoute = createFileRoute('/_authenticated')({
  pendingComponent: PageLoading,
  beforeLoad: async ({
    context,
    location,
  }: {
    context: RouterContext;
    location: ParsedLocation;
  }): Promise<void> => {
    const cached = context.queryClient.getQueryData(queryKeys.session);
    if (cached) {
      return;
    }

    try {
      await context.queryClient.fetchQuery({
        queryKey: queryKeys.session,
        queryFn: authApi.getSession,
        staleTime: CACHE_CONFIG.SESSION.staleTime,
        gcTime: CACHE_CONFIG.SESSION.gcTime,
        retry: false,
      });
    } catch (error) {
      // Only a confirmed 401 is unauthenticated; aborted loads and transient failures must not log the user out
      if (error instanceof ApiError && error.status === HTTP_STATUS.UNAUTHORIZED) {
        throw redirect({
          to: '/auth',
          search: { returnUrl: location.pathname + location.searchStr },
        });
      }
      throw error;
    }
  },
  component: AuthenticatedLayout,
});

function AuthenticatedLayout(): JSX.Element {
  const router = useRouter();

  useEffect((): (() => void) => {
    const prefetch = (): void => {
      for (const route of GREEDY_PREFETCH_ROUTES) {
        handleNavigationPromise(router.preloadRoute(route));
      }
    };

    const id = setTimeout(prefetch, PREFETCH_DELAY_MS);
    return (): void => clearTimeout(id);
  }, [router]);

  return (
    <AuthProvider>
      <BaseLayout />
    </AuthProvider>
  );
}

export { Route };
