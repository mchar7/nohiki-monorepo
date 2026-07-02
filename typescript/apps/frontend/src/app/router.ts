import type { QueryClient } from '@tanstack/react-query';
import { createRouter } from '@tanstack/react-router';
import type { ParseKeys } from 'i18next';
import { RoutePendingFallback } from '@/shared/ui/route-pending-fallback.tsx';
import { routeTree } from '../routeTree.gen.ts';

type AppRouter = ReturnType<typeof createRouter>;

function createAppRouter(queryClient: QueryClient): AppRouter {
  return createRouter({
    routeTree,
    defaultPreload: 'intent',
    defaultPreloadDelay: 50,
    // Show pending component after 300 ms to avoid spinner flash on fast connections;
    // keep it visible for at least 200 ms once displayed to prevent jarring flicker.
    defaultPendingMs: 300,
    defaultPendingMinMs: 200,
    // NOTE: `scrollRestoration: true` only restores window-level scroll via `window.scrollTo`.
    // The app's <main> element uses `overflow-auto`, so it is a nested scroll container that
    // this setting does NOT restore. For custom scroll restoration, a MainScrollRefContext ref
    // + custom hook would be required. URL search params (filters, sort, page) already survive
    // back/forward navigation correctly, handled natively by TanStack Router.

    scrollRestoration: true,
    // Enable View Transitions API for smooth page-to-page fades. Browsers without
    // support (< Chrome 111) silently skip: graceful degradation, no polyfill needed.
    defaultViewTransition: true,
    defaultPendingComponent: RoutePendingFallback,
    context: {
      queryClient,
    },
  });
}

declare module '@tanstack/react-router' {
  interface Register {
    router: AppRouter;
  }

  interface StaticDataRouteOption {
    breadcrumb?: ParseKeys<['common', 'navigation']>;
  }
}

export type { AppRouter };
export { createAppRouter };
