import { Filter, Search, X } from 'lucide-react';
import type React from 'react';
import { type JSX, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { Label } from '@/shared/ui/label.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/ui/select.tsx';
import { Switch } from '@/shared/ui/switch.tsx';
import type { JobListingsFilters } from '../lib/index.ts';

interface JobListingsFiltersBarProps {
  readonly filters: JobListingsFilters;
  readonly onSourceChange: (source: string | null) => void;
  readonly onQueryChange: (q: string | null) => void;
  readonly onClear: () => void;
  readonly hasActiveFilters: boolean;
  readonly activeFilterCount?: number | undefined;
  readonly showDismissed: boolean;
  readonly onShowDismissedChange: (show: boolean) => void;
  readonly onWorkArrangementChange: (workArrangement: string | null) => void;
  readonly onSeniorityChange: (seniority: string | null) => void;
  readonly onDateRangeChange: (dateRange: string | null) => void;
  readonly hasSalary: boolean;
  readonly onHasSalaryChange: (hasSalary: boolean) => void;
}

const SOURCE_OPTIONS = ['linkedin', 'indeed', 'glassdoor', 'company'] as const;
const WORK_ARRANGEMENT_OPTIONS = ['remote', 'hybrid', 'onsite'] as const;
const SENIORITY_OPTIONS = [
  'entry',
  'mid',
  'senior',
  'lead',
  'manager',
  'director',
  'executive',
] as const;
const DATE_RANGE_OPTIONS = ['24h', '7d', '30d'] as const;

export function JobListingsFiltersBar({
  filters,
  onSourceChange,
  onQueryChange,
  onClear,
  hasActiveFilters,
  activeFilterCount = 0,
  showDismissed,
  onShowDismissedChange,
  hasSalary,
  onHasSalaryChange,
  onWorkArrangementChange,
  onSeniorityChange,
  onDateRangeChange,
}: JobListingsFiltersBarProps): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);
  const dismissedSwitchId = useId();
  const salarySwitchId = useId();

  const handleQueryChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    onQueryChange(e.target.value || null);
  };

  const handleSourceChange = (v: string): void => {
    onSourceChange(v === 'all' ? null : v);
  };

  const handleWorkArrangementChange = (v: string): void => {
    onWorkArrangementChange(v === 'all' ? null : v);
  };

  const handleSeniorityChange = (v: string): void => {
    onSeniorityChange(v === 'all' ? null : v);
  };

  const handleDateRangeChange = (v: string): void => {
    onDateRangeChange(v === 'all' ? null : v);
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative w-60">
        <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
        <Input
          placeholder={t('jobs:filters.searchPlaceholder')}
          value={filters.q ?? ''}
          onChange={handleQueryChange}
          className="pl-8"
        />
      </div>

      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Filter className={cn('size-4', hasActiveFilters && 'text-primary')} />
        {t('jobs:filters.title')}
        {activeFilterCount > 0 ? (
          <Badge variant="secondary" className="ml-0.5 h-5 px-1.5 font-mono text-xs tabular-nums">
            {t('common:filters.activeCount', { count: activeFilterCount })}
          </Badge>
        ) : null}
      </div>

      <Select value={filters.source ?? 'all'} onValueChange={handleSourceChange}>
        <SelectTrigger className="w-40">
          <SelectValue placeholder={t('jobs:filters.sources.all')} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t('jobs:filters.sources.all')}</SelectItem>
          {SOURCE_OPTIONS.map((source) => (
            <SelectItem key={source} value={source}>
              {t(`jobs:filters.sources.${source}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={filters.workArrangement ?? 'all'} onValueChange={handleWorkArrangementChange}>
        <SelectTrigger className="w-36">
          <SelectValue placeholder={t('jobs:filters.workArrangement.all')} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t('jobs:filters.workArrangement.all')}</SelectItem>
          {WORK_ARRANGEMENT_OPTIONS.map((option) => (
            <SelectItem key={option} value={option}>
              {t(`jobs:filters.workArrangement.${option}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={filters.seniority ?? 'all'} onValueChange={handleSeniorityChange}>
        <SelectTrigger className="w-36">
          <SelectValue placeholder={t('jobs:filters.seniority.all')} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t('jobs:filters.seniority.all')}</SelectItem>
          {SENIORITY_OPTIONS.map((option) => (
            <SelectItem key={option} value={option}>
              {t(`jobs:filters.seniority.${option}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={filters.dateRange ?? 'all'} onValueChange={handleDateRangeChange}>
        <SelectTrigger className="w-40">
          <SelectValue placeholder={t('jobs:filters.dateRange.all')} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t('jobs:filters.dateRange.all')}</SelectItem>
          {DATE_RANGE_OPTIONS.map((option) => (
            <SelectItem key={option} value={option}>
              {t(`jobs:filters.dateRange.${option}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <div className="flex items-center gap-2">
        <Switch
          id={dismissedSwitchId}
          checked={showDismissed}
          onCheckedChange={onShowDismissedChange}
        />
        <Label htmlFor={dismissedSwitchId} className="cursor-pointer text-muted-foreground text-sm">
          {t('jobs:filters.showDismissed')}
        </Label>
      </div>

      <div className="flex items-center gap-2">
        <Switch id={salarySwitchId} checked={hasSalary} onCheckedChange={onHasSalaryChange} />
        <Label htmlFor={salarySwitchId} className="cursor-pointer text-muted-foreground text-sm">
          {t('jobs:filters.hasSalary')}
        </Label>
      </div>

      {hasActiveFilters ? (
        <Button variant="ghost" size="sm" onClick={onClear}>
          <X className="mr-1 size-4" />
          {t('jobs:filters.clearAll')}
        </Button>
      ) : null}
    </div>
  );
}
