import type { JSX, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/index.ts';
import { Card, CardContent } from './card.tsx';
import { Skeleton } from './skeleton.tsx';

interface CardGridSkeletonProps {
  readonly count?: number;
  readonly columns?: string;
  readonly children: (key: string) => ReactNode;
}

export function CardGridSkeleton({
  count = 6,
  columns = 'sm:grid-cols-2 lg:grid-cols-3',
  children,
}: CardGridSkeletonProps): JSX.Element {
  const { t } = useTranslation('common');
  return (
    <output className={cn('grid gap-4', columns)} aria-label={t('states.loading')} aria-busy="true">
      {Array.from({ length: count }, (_, i) => `skeleton-${i + 1}`).map((key) => children(key))}
    </output>
  );
}

interface TableSkeletonProps {
  readonly rows?: number;
  readonly columns?: number;
  readonly className?: string;
}

export function TableSkeleton({
  rows = 5,
  columns = 6,
  className,
}: TableSkeletonProps): JSX.Element {
  const { t } = useTranslation('common');
  return (
    <output
      className={cn('rounded-lg border', className)}
      aria-label={t('states.loading')}
      aria-busy="true"
    >
      <div className="border-b bg-muted/50 p-3">
        <div className="flex gap-4">
          {Array.from({ length: columns }, (_col, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: Static skeleton placeholders never reorder
            <Skeleton key={`th-${i}`} className="h-4 flex-1" />
          ))}
        </div>
      </div>
      {Array.from({ length: rows }, (_row, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: Static skeleton placeholders never reorder
        <div key={`tr-${i}`} className="flex items-center gap-4 border-b p-3 last:border-0">
          {Array.from({ length: columns }, (_col, j) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: Static skeleton placeholders never reorder
            <Skeleton key={`td-${i}-${j}`} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </output>
  );
}

interface CardListSkeletonProps {
  readonly count?: number;
  readonly className?: string;
}

export function CardListSkeleton({ count = 3, className }: CardListSkeletonProps): JSX.Element {
  const { t } = useTranslation('common');
  return (
    <output
      className={cn('flex flex-col gap-4', className)}
      aria-label={t('states.loading')}
      aria-busy="true"
    >
      {Array.from({ length: count }, (_item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: Static skeleton placeholders never reorder
        <Card key={`card-${i}`}>
          <CardContent className="p-4">
            <Skeleton className="h-24 w-full" />
          </CardContent>
        </Card>
      ))}
    </output>
  );
}
