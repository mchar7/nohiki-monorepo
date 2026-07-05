import { Maximize2, Minus, Plus } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui/button.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/shared/ui/tooltip.tsx';
import type { ScaleState } from '../model/index.ts';

interface ScaleControlsProps {
  readonly scale: ScaleState;
  readonly onZoomIn: () => void;
  readonly onZoomOut: () => void;
  readonly onSetScaleMode: (mode: ScaleState['mode']) => void;
  readonly disabled?: boolean;
  /** Hide the "Fit" button (use when already in fullscreen mode) */
  readonly hideFitButton?: boolean;
}

export function ScaleControls({
  scale,
  onZoomIn,
  onZoomOut,
  onSetScaleMode,
  disabled = false,
  hideFitButton = false,
}: ScaleControlsProps): JSX.Element {
  const { t } = useTranslation('omakase.preview');

  const handleFitClick = (): void => {
    onSetScaleMode('fit');
  };

  const fitButtonVariant: 'secondary' | 'ghost' = scale.mode === 'fit' ? 'secondary' : 'ghost';

  return (
    <TooltipProvider>
      <div className="flex items-center gap-1">
        {/* Zoom controls */}
        <Tooltip>
          <TooltipTrigger asChild={true}>
            <Button
              variant="ghost"
              size="icon"
              onClick={onZoomOut}
              disabled={disabled}
              className="size-7"
              aria-label={t('scale.zoomOut')}
            >
              <Minus className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('scale.zoomOut')}</TooltipContent>
        </Tooltip>

        {/* Scale display */}
        <span className="min-w-14 text-center text-muted-foreground text-xs tabular-nums">
          {`${Math.round(scale.percentage)}%`}
        </span>

        <Tooltip>
          <TooltipTrigger asChild={true}>
            <Button
              variant="ghost"
              size="icon"
              onClick={onZoomIn}
              disabled={disabled}
              className="size-7"
              aria-label={t('scale.zoomIn')}
            >
              <Plus className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('scale.zoomIn')}</TooltipContent>
        </Tooltip>

        {/* Fit button - hidden in fullscreen mode where it's not useful */}
        {!hideFitButton && (
          <Tooltip>
            <TooltipTrigger asChild={true}>
              <Button
                variant={fitButtonVariant}
                size="sm"
                onClick={handleFitClick}
                disabled={disabled}
                className="h-7 px-2 text-xs"
              >
                <Maximize2 className="mr-1 size-3.5" />
                {t('scale.fitToWidth')}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t('scale.fitToWidth')}</TooltipContent>
          </Tooltip>
        )}
      </div>
    </TooltipProvider>
  );
}
