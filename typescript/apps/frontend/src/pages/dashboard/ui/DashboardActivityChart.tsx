import { Download, Info } from 'lucide-react';
import type { JSX } from 'react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Area, AreaChart, CartesianGrid, Line, XAxis } from 'recharts';

import { exportToCsv } from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/shared/ui/chart.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/ui/select.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { ToggleGroup, ToggleGroupItem } from '@/shared/ui/toggle-group.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/shared/ui/tooltip.tsx';
import {
  type ActivityDataPoint,
  aggregateCorrelationsByDate,
  computeTrendSummary,
  type TrendSummary,
  withMovingAverage,
} from '../lib/index.ts';
import type { DashboardActivityChartProps } from './Dashboard.types.ts';

type TimeRangeValue = '7d' | '30d' | '90d';

const TIME_RANGE_DAYS: Record<TimeRangeValue, number> = {
  '7d': 7,
  '30d': 30,
  '90d': 90,
};

const TREND_COLOR: Record<TrendSummary['direction'], string> = {
  up: 'text-green-600',
  down: 'text-amber-600',
  steady: 'text-muted-foreground',
};

function isTimeRangeValue(value: string): value is TimeRangeValue {
  return value === '7d' || value === '30d' || value === '90d';
}

function ChartLoadingSkeleton(): JSX.Element {
  return (
    <Card className="@container/card">
      <CardHeader className="relative">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="mt-1 h-4 w-64" />
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        <Skeleton className="h-44 w-full" />
      </CardContent>
    </Card>
  );
}

/** Renders the time range toggle + dropdown controls. */
function TimeRangeControls({
  timeRange,
  onTimeRangeChange,
}: {
  readonly timeRange: TimeRangeValue;
  readonly onTimeRangeChange: (value: string) => void;
}): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <div className="absolute top-4 right-4">
      <ToggleGroup
        type="single"
        value={timeRange}
        onValueChange={onTimeRangeChange}
        className="@[767px]/card:flex hidden"
      >
        <ToggleGroupItem value="90d" className="h-8 px-2.5">
          {t('activity.timeRange.days90')}
        </ToggleGroupItem>
        <ToggleGroupItem value="30d" className="h-8 px-2.5">
          {t('activity.timeRange.days30')}
        </ToggleGroupItem>
        <ToggleGroupItem value="7d" className="h-8 px-2.5">
          {t('activity.timeRange.days7')}
        </ToggleGroupItem>
      </ToggleGroup>
      <Select value={timeRange} onValueChange={onTimeRangeChange}>
        <SelectTrigger
          className="flex @[767px]/card:hidden w-40"
          aria-label={t('activity.selectTimeRange')}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent className="rounded-xl">
          <SelectItem value="90d" className="rounded-lg">
            {t('activity.timeRange.last90')}
          </SelectItem>
          <SelectItem value="30d" className="rounded-lg">
            {t('activity.timeRange.last30')}
          </SelectItem>
          <SelectItem value="7d" className="rounded-lg">
            {t('activity.timeRange.last7')}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

/** Chart header with title, info tooltip, and export button. */
function ChartHeader({
  title,
  onExport,
}: {
  readonly title: string;
  readonly onExport: () => void;
}): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <div className="flex items-center gap-2">
      <CardTitle className="text-base">{title}</CardTitle>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild={true}>
            <Button
              variant="ghost"
              size="icon"
              className="size-6"
              aria-label={t('activity.chartInfoAriaLabel')}
            >
              <Info className="size-3.5 text-muted-foreground" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="right">{t('activity.chartInfo')}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild={true}>
            <Button variant="ghost" size="icon" className="size-7" onClick={onExport}>
              <Download className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('actions.export')}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}

function DashboardActivityChart({
  correlations,
  isLoading,
}: DashboardActivityChartProps): JSX.Element {
  const { t, i18n } = useTranslation('dashboard');
  const gradientId = useId();
  const [timeRange, setTimeRange] = useState<TimeRangeValue>('30d');

  const chartConfig: ChartConfig = {
    matches: { label: t('activity.series.matches'), color: 'var(--primary)' },
    trend: { label: t('activity.series.trend'), color: 'var(--muted-foreground)' },
  };

  const chartData = withMovingAverage(
    aggregateCorrelationsByDate(correlations, TIME_RANGE_DAYS[timeRange]),
  );

  const trendSummary = computeTrendSummary(
    chartData.map((point) => ({ date: point.date, count: point.matches })),
  );

  const formatDate = (value: unknown): string =>
    new Date(String(value)).toLocaleDateString(i18n.language, { month: 'short', day: 'numeric' });

  const handleTimeRangeChange = (value: string): void => {
    if (value && isTimeRangeValue(value)) {
      setTimeRange(value);
    }
  };

  if (isLoading) {
    return <ChartLoadingSkeleton />;
  }

  return (
    <Card className="@container/card">
      <CardHeader className="relative pb-2">
        <ChartHeader
          title={t('activity.title')}
          onExport={() => exportToCsv(chartData, `activity-${timeRange}`)}
        />
        <CardDescription className={TREND_COLOR[trendSummary.direction]}>
          {t(`activity.trend.${trendSummary.direction}`, { percent: trendSummary.percentChange })}
        </CardDescription>
        <TimeRangeControls timeRange={timeRange} onTimeRangeChange={handleTimeRangeChange} />
      </CardHeader>
      <CardContent className="px-2 pt-2 sm:px-4">
        <ActivityAreaChart
          data={chartData}
          config={chartConfig}
          gradientId={gradientId}
          formatDate={formatDate}
        />
      </CardContent>
    </Card>
  );
}

/** Renders the area chart with trend line overlay. */
function ActivityAreaChart({
  data,
  config,
  gradientId,
  formatDate,
}: {
  readonly data: readonly ActivityDataPoint[];
  readonly config: ChartConfig;
  readonly gradientId: string;
  readonly formatDate: (value: unknown) => string;
}): JSX.Element {
  return (
    <ChartContainer config={config} className="aspect-auto h-40 w-full">
      <AreaChart data={data} accessibilityLayer={true}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--color-matches)" stopOpacity={0.8} />
            <stop offset="95%" stopColor="var(--color-matches)" stopOpacity={0.1} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={32}
          tickFormatter={formatDate}
        />
        <ChartTooltip
          cursor={false}
          content={<ChartTooltipContent labelFormatter={formatDate} indicator="dot" />}
        />
        <Area
          dataKey="matches"
          type="natural"
          fill={`url(#${gradientId})`}
          stroke="var(--color-matches)"
        />
        <Line
          dataKey="trend"
          type="natural"
          stroke="var(--color-trend)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
          connectNulls={true}
        />
      </AreaChart>
    </ChartContainer>
  );
}

export { DashboardActivityChart };
