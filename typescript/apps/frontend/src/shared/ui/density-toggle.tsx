import { AlignCenter, AlignJustify, AlignLeft } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import type { Density } from '@/shared/lib/hooks/useDensity.ts';
import { useDensity } from '@/shared/lib/hooks/useDensity.ts';
import { cn } from '@/shared/lib/utils/utils.ts';
import type { DensityToggleProps } from './density-toggle.types.ts';
import { ToggleGroup, ToggleGroupItem } from './toggle-group.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './tooltip.tsx';

const DENSITY_OPTIONS: readonly {
  readonly value: Density;
  readonly icon: typeof AlignLeft;
  readonly labelKey: string;
}[] = [
  { value: 'compact', icon: AlignLeft, labelKey: 'density.compact' },
  { value: 'comfortable', icon: AlignCenter, labelKey: 'density.comfortable' },
  { value: 'spacious', icon: AlignJustify, labelKey: 'density.spacious' },
];

/** Toggle group for selecting display density (compact/comfortable/spacious).
 *  Reads and writes density via the global Zustand store. */
function DensityToggle({ className }: DensityToggleProps): JSX.Element {
  const { t } = useTranslation();
  const { density, setDensity } = useDensity();

  const handleValueChange = (value: string): void => {
    if (value) {
      setDensity(value as Density);
    }
  };

  return (
    <TooltipProvider>
      <ToggleGroup
        type="single"
        value={density}
        onValueChange={handleValueChange}
        variant="outline"
        size="sm"
        className={cn('gap-0.5', className)}
        aria-label={t('density.label')}
      >
        {DENSITY_OPTIONS.map(({ value, icon: Icon, labelKey }) => (
          <Tooltip key={value}>
            <TooltipTrigger asChild={true}>
              <ToggleGroupItem value={value} aria-label={t(labelKey)}>
                <Icon className="size-4" />
              </ToggleGroupItem>
            </TooltipTrigger>
            <TooltipContent>{t(labelKey)}</TooltipContent>
          </Tooltip>
        ))}
      </ToggleGroup>
    </TooltipProvider>
  );
}

export { DensityToggle };
