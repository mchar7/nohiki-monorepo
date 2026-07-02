import { Sparkles, Target, ThumbsUp, TrendingUp } from 'lucide-react';

const SCORE_PERCENT_SCALE: number = 100;

import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '@/shared/lib';
import { Badge } from '@/shared/ui/badge.tsx';
import { Card } from '@/shared/ui/card.tsx';

interface MatchStats {
  total: number;
  highQuality: number;
  newThisWeek: number;
  saved: number;
}

interface MatchesStatsCardsProps {
  readonly stats: MatchStats;
  readonly isLoading?: boolean | undefined;
}

function StatCard({
  title,
  value,
  icon: Icon,
  badge,
  isLoading,
}: {
  readonly title: string;
  readonly value: number;
  readonly icon: React.ComponentType<{ className?: string }>;
  readonly badge?: { label: string; trend: 'up' | 'neutral' } | undefined;
  readonly isLoading?: boolean | undefined;
}): JSX.Element {
  const valueContent = isLoading ? (
    <div className="h-8 w-16 animate-pulse rounded bg-muted" />
  ) : (
    <span className="font-bold text-2xl tabular-nums">{formatNumber(value)}</span>
  );
  const badgeClassName =
    badge?.trend === 'up'
      ? 'border-green-500/20 bg-green-500/10 text-green-700 dark:text-green-400'
      : '';

  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex size-8 items-center justify-center rounded-md bg-primary/10">
          <Icon className="size-4 text-primary" />
        </div>
        <span className="font-medium text-sm">{title}</span>
      </div>
      <div className="flex items-baseline gap-2">
        {valueContent}
        {badge && !isLoading && (
          <Badge variant="outline" className={badgeClassName}>
            {badge.trend === 'up' && <TrendingUp className="mr-1 size-3" />}
            {badge.label}
          </Badge>
        )}
      </div>
    </Card>
  );
}

export function MatchesStatsCards({ stats, isLoading }: MatchesStatsCardsProps): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  const totalBadge: { label: string; trend: 'up' | 'neutral' } | undefined =
    stats.newThisWeek > 0
      ? { label: `+${formatNumber(stats.newThisWeek)}`, trend: 'up' }
      : undefined;
  const highQualityBadge: { label: string; trend: 'up' | 'neutral' } | undefined =
    stats.highQuality > 0
      ? {
          label: `${Math.round((stats.highQuality / Math.max(stats.total, 1)) * SCORE_PERCENT_SCALE)}%`,
          trend: 'neutral',
        }
      : undefined;

  const cards = [
    {
      title: t('jobs:match.totalMatches'),
      value: stats.total,
      icon: Target,
      badge: totalBadge,
    },
    {
      title: t('jobs:match.stats.newThisWeek'),
      value: stats.newThisWeek,
      icon: Sparkles,
    },
    {
      title: t('jobs:status.SAVED'),
      value: stats.saved,
      icon: ThumbsUp,
    },
    {
      title: t('common:labels.highQuality'),
      value: stats.highQuality,
      icon: TrendingUp,
      badge: highQualityBadge,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <StatCard
          key={card.title}
          title={card.title}
          value={card.value}
          icon={card.icon}
          badge={card.badge}
          isLoading={isLoading}
        />
      ))}
    </div>
  );
}
