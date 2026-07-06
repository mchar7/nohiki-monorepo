import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * Full-viewport loading spinner for app bootstrap and top-level route transitions.
 *
 * Uses `min-h-screen` to fill the entire viewport. Appropriate for:
 * - `LocalStoreInitializer` in `main.tsx` (initial app load)
 * - `_authenticated` route's `pendingComponent` (session fetch replaces full viewport)
 *
 * For content-area spinners inside the sidebar layout, use `RoutePendingFallback` instead.
 */
export function PageLoading(): JSX.Element {
  const { t } = useTranslation('common');

  return (
    <output
      className="flex min-h-screen items-center justify-center"
      data-testid="page-loading"
      aria-label={t('a11y.pageLoading')}
    >
      <div className="size-8 animate-spin rounded-full border-primary border-b-2" />
    </output>
  );
}
