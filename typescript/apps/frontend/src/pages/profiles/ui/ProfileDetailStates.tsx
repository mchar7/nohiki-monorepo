import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';

export function ProfileDetailSkeleton(): JSX.Element {
  return (
    <PageLayout contentWidth="narrow" className="space-y-6">
      {/* PageHeader: back button (h-9 icon button) + title (text-2xl = h-8) */}
      <div className="flex items-center gap-4">
        <Skeleton className="size-9 rounded-md" />
        <Skeleton className="h-8 w-48" />
      </div>
      {/* ProfileViewCard: CardHeader (title + description) + sections */}
      <Card>
        <CardContent className="space-y-6 pt-6">
          <div className="space-y-1.5">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-4 w-28" />
          </div>
          {/* Keywords section: label (text-sm h-5) + badge row */}
          <div className="space-y-2">
            <Skeleton className="h-5 w-32" />
            <div className="flex gap-1.5">
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-6 w-20 rounded-full" />
              <Skeleton className="h-6 w-14 rounded-full" />
            </div>
          </div>
          {/* Work arrangements section */}
          <div className="space-y-2">
            <Skeleton className="h-5 w-36" />
            <div className="flex gap-1.5">
              <Skeleton className="h-6 w-16 rounded-full" />
              <Skeleton className="h-6 w-14 rounded-full" />
            </div>
          </div>
          {/* Threshold cards: grid with 2 rounded-lg border cards */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 rounded-lg border p-4">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-8 w-12" />
            </div>
            <div className="space-y-2 rounded-lg border p-4">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-8 w-12" />
            </div>
          </div>
        </CardContent>
      </Card>
    </PageLayout>
  );
}

export function ProfileNotFound(): JSX.Element {
  const { t } = useTranslation(['common']);

  return (
    <PageLayout>
      <Card>
        <CardContent className="py-12 text-center">
          <p className="text-muted-foreground">{t('common:empty.noData')}</p>
          <Button asChild={true} className="mt-4">
            <a href={ROUTE_PATHS.PROFILES.LIST}>{t('common:actions.goBack')}</a>
          </Button>
        </CardContent>
      </Card>
    </PageLayout>
  );
}
