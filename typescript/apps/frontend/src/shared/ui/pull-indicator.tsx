import { RefreshCw } from 'lucide-react';
import type { JSX } from 'react';
import { PULL_THRESHOLD_PX } from '@/shared/lib/index.ts';
import type { PullIndicatorProps } from './pull-indicator.types.ts';

/** Full rotation degrees at pull threshold. */
const FULL_ROTATION_DEG: number = 360;

/** Visual indicator for pull-to-refresh gesture.
 *
 *  Shows a rotating RefreshCw icon whose opacity and rotation scale
 *  linearly with `pullDistance`. Spins continuously while `isRefreshing`.
 *  Renders nothing when idle (pullDistance === 0 and not refreshing). */
function PullIndicator({ pullDistance, isRefreshing }: PullIndicatorProps): JSX.Element | null {
  if (pullDistance === 0 && !isRefreshing) {
    return null;
  }

  const progress = Math.min(pullDistance / PULL_THRESHOLD_PX, 1);
  const rotation = progress * FULL_ROTATION_DEG;

  return (
    <div className="flex justify-center py-2" aria-hidden="true">
      <RefreshCw
        className={
          isRefreshing
            ? 'size-5 animate-spin text-muted-foreground'
            : 'size-5 text-muted-foreground'
        }
        style={
          isRefreshing
            ? undefined
            : {
                opacity: progress,
                transform: `rotate(${String(rotation)}deg)`,
              }
        }
      />
    </div>
  );
}

export { PullIndicator };
