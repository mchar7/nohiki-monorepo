import { type AnyRootRoute, createRootRouteWithContext, Outlet } from '@tanstack/react-router';
import type { JSX } from 'react';
import { type ComponentType, type LazyExoticComponent, lazy } from 'react';
import type { RouterContext } from '@/app/router-context.ts';
import { NotFound } from '@/pages/not-found/index.ts';
import { Toaster } from '@/shared/ui/sonner.tsx';

// Devtools component accepts position and additional router-devtools-specific props
type DevtoolsComponent =
  | LazyExoticComponent<ComponentType<{ position?: string; [key: string]: unknown }>>
  | (() => null);

const TanStackRouterDevtools: DevtoolsComponent =
  import.meta.env.DEV &&
  import.meta.env.VITE_ENABLE_DEVTOOLS === 'true' &&
  !import.meta.env.VITE_E2E
    ? (lazy(async () => {
        const { TanStackRouterDevtools: Devtools } = await import(
          '@tanstack/react-router-devtools'
        );
        return {
          default: Devtools as ComponentType<{ position?: string; [key: string]: unknown }>,
        };
      }) as DevtoolsComponent)
    : (): null => null;

const Route: AnyRootRoute = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
  notFoundComponent: NotFound,
});

function RootComponent(): JSX.Element {
  return (
    <>
      <Outlet />
      <Toaster position="bottom-right" richColors={true} closeButton={true} />
      <TanStackRouterDevtools position="bottom-right" />
    </>
  );
}

export { Route };
