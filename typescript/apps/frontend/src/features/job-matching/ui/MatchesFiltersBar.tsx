import { Filter, X } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { ProfileResponse } from '@/shared/api';
import { cn } from '@/shared/lib';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/ui/select.tsx';
import { Slider } from '@/shared/ui/slider.tsx';

interface MatchesFiltersBarProps {
  readonly profiles: readonly ProfileResponse[];
  readonly selectedPrefId: string | null;
  readonly minScore: number | null;
  readonly onPrefIdChange: (value: string | null) => void;
  readonly onMinScoreChange: (value: number | null) => void;
  readonly onClear: () => void;
  readonly hasActiveFilters: boolean;
  readonly activeFilterCount?: number | undefined;
}

export function MatchesFiltersBar({
  profiles,
  selectedPrefId,
  minScore,
  onPrefIdChange,
  onMinScoreChange,
  onClear,
  hasActiveFilters,
  activeFilterCount = 0,
}: MatchesFiltersBarProps): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  const handlePrefIdChange = (value: string): void => {
    if (value === 'all') {
      onPrefIdChange(null);
    } else {
      onPrefIdChange(value);
    }
  };

  const handleMinScoreChange = ([value = 60]: number[]): void => {
    onMinScoreChange(value === 60 ? null : value);
  };

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-1 flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Filter
            className={cn('size-4 text-muted-foreground', hasActiveFilters && 'text-primary')}
          />
          <span className="font-medium text-sm">{t('jobs:filters.title')}</span>
          {activeFilterCount > 0 ? (
            <Badge variant="secondary" className="ml-0.5 h-5 px-1.5 font-mono text-xs tabular-nums">
              {t('common:filters.activeCount', { count: activeFilterCount })}
            </Badge>
          ) : null}
        </div>

        <Select value={selectedPrefId ?? 'all'} onValueChange={handlePrefIdChange}>
          <SelectTrigger className="w-45">
            <SelectValue placeholder={t('jobs:pages.matches.filterByTarget')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('jobs:pages.matches.allTargets')}</SelectItem>
            {profiles.map((profile) => (
              <SelectItem key={profile.id} value={profile.id}>
                {profile.pref_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-2">
          <span className="whitespace-nowrap text-muted-foreground text-sm">
            {`${t('jobs:pages.matches.minScore')}:`}
          </span>
          <div className="w-32">
            <Slider
              value={[minScore ?? 60]}
              onValueChange={handleMinScoreChange}
              max={100}
              step={5}
              className="cursor-pointer"
            />
          </div>
          <span className="w-10 font-mono text-sm tabular-nums">{`${minScore ?? 60} / 100`}</span>
        </div>
      </div>

      {hasActiveFilters ? (
        <Button variant="ghost" size="sm" onClick={onClear} className="text-muted-foreground">
          <X className="mr-1 size-4" />
          {t('jobs:filters.clearAll')}
        </Button>
      ) : null}
    </div>
  );
}
