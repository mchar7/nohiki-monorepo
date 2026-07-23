import type { LucideIcon } from 'lucide-react';
import { Bookmark, Briefcase, FileText, User } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { Card } from '@/shared/ui/card.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import type { StatTrend } from '../lib/index.ts';
import type { DashboardStatsCardsProps } from './Dashboard.types.ts';

interface StatCardProps {
  readonly icon: LucideIcon;
  readonly title: string;
  readonly value: number;
  readonly description: string;
  readonly isLoading?: boolean | undefined;
  readonly trend?: StatTrend | undefined;
}

function TrendIndicator({ trend }: { readonly trend: StatTrend }): JSX.Element | null {
  const { t } = useTranslation('dashboard');

  if (trend.direction === 'unavailable') {
    return null;
  }

  const config: Record<'up' | 'down' | 'steady', { symbol: string; className: string }> = {
    up: { symbol: '↑', className: 'text-green-600 text-xs' },
    down: { symbol: '↓', className: 'text-amber-600 text-xs' },
    steady: { symbol: '→', className: 'text-muted-foreground text-xs' },
  };

  const { symbol, className } = config[trend.direction];
  const absDelta = Math.abs(trend.delta);

  return (
    <output
      className={className}
      aria-label={t('stats.trend.ariaLabel', {
        direction: t(`stats.trend.${trend.direction}`),
        delta: absDelta,
      })}
    >
      {symbol} {absDelta}
    </output>
  );
}

function StatCard({
  icon: Icon,
  title,
  value,
  description,
  isLoading,
  trend,
}: StatCardProps): JSX.Element {
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex size-7 items-center justify-center rounded-md bg-primary/10">
          <Icon className="size-3.5 text-primary" />
        </div>
        <span className="font-medium text-sm">{title}</span>
      </div>
      <div className="flex items-baseline gap-2">
        {isLoading ? <Skeleton className="h-8 w-14" /> : null}
        {isLoading ? null : (
          <span className="font-bold text-3xl tabular-nums">{value.toLocaleString()}</span>
        )}
        <span className="text-muted-foreground text-xs">{description}</span>
      </div>
      {trend ? <TrendIndicator trend={trend} /> : null}
    </Card>
  );
}

function DashboardStatsCards({ stats, isLoading }: DashboardStatsCardsProps): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <StatCard
        icon={Briefcase}
        title={t('stats.jobMatches.title')}
        value={stats.jobMatches}
        description={t('stats.jobMatches.description')}
        isLoading={isLoading}
        trend={stats.trends?.jobMatches}
      />
      <StatCard
        icon={User}
        title={t('stats.profiles.title')}
        value={stats.profiles}
        description={t('stats.profiles.description')}
        isLoading={isLoading}
      />
      <StatCard
        icon={FileText}
        title={t('stats.documents.title')}
        value={stats.documents}
        description={t('stats.documents.description')}
        isLoading={isLoading}
        trend={stats.trends?.documents}
      />
      <StatCard
        icon={Bookmark}
        title={t('stats.savedJobs.title')}
        value={stats.savedJobs}
        description={t('stats.savedJobs.description')}
        isLoading={isLoading}
      />
    </div>
  );
}

export { DashboardStatsCards };
