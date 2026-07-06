import { ArrowDownAZ, ArrowUpAZ } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib/utils/utils.ts';
import { Button } from './button.tsx';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './select.tsx';
import type { SortSelectProps } from './sort-select.types.ts';

/**
 * Sort dropdown with direction toggle for list pages.
 * Provides a field selector and asc/desc toggle button.
 */
function SortSelect({
  options,
  value,
  direction,
  onValueChange,
  onDirectionChange,
  className,
}: SortSelectProps): JSX.Element {
  const { t } = useTranslation('common');

  const toggleDirection = (): void => {
    onDirectionChange(direction === 'asc' ? 'desc' : 'asc');
  };

  const directionLabel =
    direction === 'asc' ? t('sort.ascending', 'Ascending') : t('sort.descending', 'Descending');

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger className="w-44" aria-label={t('sort.sortBy', 'Sort by')}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="outline"
        size="icon"
        onClick={toggleDirection}
        aria-label={directionLabel}
        title={directionLabel}
      >
        {direction === 'asc' ? (
          <ArrowDownAZ className="size-4" />
        ) : (
          <ArrowUpAZ className="size-4" />
        )}
      </Button>
    </div>
  );
}

export { SortSelect };
