import type { JSX } from 'react';
import { LoadingSpinner } from './loading-spinner.tsx';

/**
 * Route-level pending component for TanStack Router's `pendingComponent` prop.
 *
 * Fills the content area with a centered spinner while a route loader is in flight.
 * Only rendered after the router's `pendingMs` threshold is exceeded, preventing
 * a flash of loading state on fast connections.
 */
export function RoutePendingFallback(): JSX.Element {
  return (
    <div data-testid="route-pending-fallback">
      <LoadingSpinner size="lg" />
    </div>
  );
}
