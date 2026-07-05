/** Number of decimal places for the aspect ratio display */
const ASPECT_RATIO_DECIMAL_PLACES: number = 3;

import type { ChangeEvent, JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import type { PresetKey } from '../lib/page-size.ts';
import type { PageSize } from '../model/index.ts';
import {
  CompactDimensionInputs,
  CustomSizeDialog,
  FullDimensionEditor,
  PresetSelector,
} from './page-size-components.tsx';
import { usePageSizeHandlers } from './usePageSizeHandlers.ts';

interface PageSizeEditorProps {
  readonly pageSize: PageSize;
  readonly onChange: (pageSize: PageSize) => void;
  readonly compact?: boolean;
}

interface HandlerBag {
  readonly currentPreset: PresetKey;
  readonly isCustom: boolean;
  readonly unitSuffix: string;
  readonly customDialogOpen: boolean;
  readonly setCustomDialogOpen: (open: boolean) => void;
  readonly customWidth: string;
  readonly customHeight: string;
  readonly customUnit: 'mm' | 'in';
  readonly setCustomUnit: (unit: 'mm' | 'in') => void;
  readonly handlePresetChange: (preset: PresetKey) => void;
  readonly handleCustomDialogSubmit: () => void;
  readonly handleSwapDimensions: () => void;
  readonly handleWidthInput: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly handleHeightInput: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly handleUnitChange: (unit: 'mm' | 'in') => void;
  readonly handleCustomWidthInput: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly handleCustomHeightInput: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly handleCancelDialog: () => void;
}

function PageSizeDialogFragment({
  h,
  t,
}: {
  readonly h: HandlerBag;
  readonly t: (key: string) => string;
}): JSX.Element {
  return (
    <CustomSizeDialog
      open={h.customDialogOpen}
      onOpenChange={h.setCustomDialogOpen}
      customWidth={h.customWidth}
      customHeight={h.customHeight}
      customUnit={h.customUnit}
      onWidthChange={h.handleCustomWidthInput}
      onHeightChange={h.handleCustomHeightInput}
      onUnitChange={h.setCustomUnit}
      onSubmit={h.handleCustomDialogSubmit}
      onCancel={h.handleCancelDialog}
      t={t}
    />
  );
}

function CompactPageSizeView({
  pageSize,
  currentPreset,
  isCustom,
  unitSuffix,
  onPresetChange,
  onWidthInput,
  onHeightInput,
  onUnitChange,
  onSwap,
  t,
}: {
  readonly pageSize: PageSize;
  readonly currentPreset: PresetKey;
  readonly isCustom: boolean;
  readonly unitSuffix: string;
  readonly onPresetChange: (preset: PresetKey) => void;
  readonly onWidthInput: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly onHeightInput: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly onUnitChange: (unit: 'mm' | 'in') => void;
  readonly onSwap: () => void;
  readonly t: (key: string) => string;
}): JSX.Element {
  return (
    <div className="flex items-center gap-3">
      <PresetSelector
        currentPreset={currentPreset}
        onPresetChange={onPresetChange}
        compact={true}
        t={t}
      />
      {isCustom ? (
        <CompactDimensionInputs
          pageSize={pageSize}
          onWidthChange={onWidthInput}
          onHeightChange={onHeightInput}
          onUnitChange={onUnitChange}
          onSwap={onSwap}
          t={t}
        />
      ) : (
        <div className="flex h-10 items-center rounded-md border border-input bg-muted/30 px-4 text-muted-foreground text-sm">
          {`${pageSize.width}${unitSuffix} × ${pageSize.height}${unitSuffix}`}
        </div>
      )}
    </div>
  );
}

export function PageSizeEditor({
  pageSize,
  onChange,
  compact = false,
}: PageSizeEditorProps): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');
  const h = usePageSizeHandlers(pageSize, onChange);

  if (compact) {
    return (
      <>
        <CompactPageSizeView
          pageSize={pageSize}
          currentPreset={h.currentPreset}
          isCustom={h.isCustom}
          unitSuffix={h.unitSuffix}
          onPresetChange={h.handlePresetChange}
          onWidthInput={h.handleWidthInput}
          onHeightInput={h.handleHeightInput}
          onUnitChange={h.handleUnitChange}
          onSwap={h.handleSwapDimensions}
          t={t}
        />
        <PageSizeDialogFragment h={h} t={t} />
      </>
    );
  }

  const aspectRatio = (pageSize.width / pageSize.height).toFixed(ASPECT_RATIO_DECIMAL_PLACES);
  const orientation: 'portrait' | 'landscape' =
    pageSize.width < pageSize.height ? 'portrait' : 'landscape';

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base">{t('pageSize.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <PresetSelector
          currentPreset={h.currentPreset}
          onPresetChange={h.handlePresetChange}
          t={t}
        />
        <FullDimensionEditor
          pageSize={pageSize}
          isCustom={h.isCustom}
          onWidthChange={h.handleWidthInput}
          onHeightChange={h.handleHeightInput}
          onUnitChange={h.handleUnitChange}
          onSwap={h.handleSwapDimensions}
          t={t}
        />
        <div className="flex items-center justify-between text-muted-foreground text-sm">
          <span>{t('pageSize.aspectRatio', { ratio: aspectRatio })}</span>
          <span className="capitalize">{t(`pageSize.${orientation}`)}</span>
        </div>
      </CardContent>
      <PageSizeDialogFragment h={h} t={t} />
    </Card>
  );
}
