import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { usePendingMutations } from '@/shared/lib/index.ts';
import { cn } from '@/shared/lib/utils/utils.ts';
import type { PendingMutationBadgeProps } from './pending-mutation-badge.types.ts';

/**
 * Displays a small "Syncing..." indicator when there are in-flight
 * mutations for the given entity type. Renders nothing when idle.
 */
function PendingMutationBadge({
  entityType,
  className,
}: PendingMutationBadgeProps): JSX.Element | null {
  const { t } = useTranslation(['common']);
  const { isEntityPending } = usePendingMutations();

  if (!isEntityPending(entityType)) {
    return null;
  }

  return (
    <span className={cn('inline-flex items-center gap-1 text-muted-foreground text-xs', className)}>
      <Loader2 className="size-3 animate-spin" aria-hidden="true" />
      {t('common:states.syncing')}
    </span>
  );
}

export { PendingMutationBadge };
