import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { Card, CardContent, CardHeader } from '@/shared/ui/card.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';

/** Number of stat card placeholders in the skeleton grid */
const STAT_CARD_COUNT: number = 4;

/** Dashboard loading skeleton with stat cards, highlight cards, and chart placeholder. */
function DashboardSkeleton(): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <output className="block space-y-6" aria-label={t('skeleton.ariaLabel')} aria-busy="true">
      {/* Stat cards skeleton */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {Array.from({ length: STAT_CARD_COUNT }, (_, i) => i).map((i) => (
          <Card key={i} className="p-4">
            <div className="mb-2 flex items-center gap-2">
              <Skeleton className="size-7 rounded-md" />
              <Skeleton className="h-4 w-20" />
            </div>
            <Skeleton className="h-8 w-14" />
          </Card>
        ))}
      </div>

      {/* Highlight cards skeleton */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {Array.from({ length: 2 }, (_, i) => i).map((i) => (
          <Card key={i}>
            <CardHeader className="pb-2">
              <div className="flex items-center gap-2">
                <Skeleton className="size-7 rounded-md" />
                <Skeleton className="h-5 w-28" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Chart skeleton */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-40" />
          <Skeleton className="mt-1 h-4 w-64" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-44 w-full" />
        </CardContent>
      </Card>
    </output>
  );
}

export { DashboardSkeleton };
