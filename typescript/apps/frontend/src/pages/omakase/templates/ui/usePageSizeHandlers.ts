import type { ChangeEvent } from 'react';
import { useState } from 'react';
import type { PresetKey } from '../lib/page-size.ts';
import { detectPreset, PAGE_PRESETS } from '../lib/page-size.ts';
import type { PageSize } from '../model/index.ts';

interface PageSizeHandlers {
  currentPreset: PresetKey;
  isCustom: boolean;
  unitSuffix: string;
  customDialogOpen: boolean;
  setCustomDialogOpen: (open: boolean) => void;
  customWidth: string;
  customHeight: string;
  customUnit: 'mm' | 'in';
  setCustomUnit: (unit: 'mm' | 'in') => void;
  handlePresetChange: (preset: PresetKey) => void;
  handleCustomDialogSubmit: () => void;
  handleSwapDimensions: () => void;
  handleWidthInput: (e: ChangeEvent<HTMLInputElement>) => void;
  handleHeightInput: (e: ChangeEvent<HTMLInputElement>) => void;
  handleUnitChange: (unit: 'mm' | 'in') => void;
  handleCustomWidthInput: (e: ChangeEvent<HTMLInputElement>) => void;
  handleCustomHeightInput: (e: ChangeEvent<HTMLInputElement>) => void;
  handleCancelDialog: () => void;
}

/** Encapsulates all PageSizeEditor state and event handlers. */
export function usePageSizeHandlers(
  pageSize: PageSize,
  onChange: (ps: PageSize) => void,
): PageSizeHandlers {
  const [customDialogOpen, setCustomDialogOpen] = useState(false);
  const [customWidth, setCustomWidth] = useState(pageSize.width.toString());
  const [customHeight, setCustomHeight] = useState(pageSize.height.toString());
  const [customUnit, setCustomUnit] = useState<'mm' | 'in'>(pageSize.unit);

  const currentPreset = detectPreset(pageSize);

  const parseAndApply = (value: string, field: 'width' | 'height'): void => {
    const parsed = Number.parseFloat(value);
    if (!Number.isNaN(parsed) && parsed > 0) {
      onChange({ ...pageSize, [field]: parsed });
    }
  };

  return {
    currentPreset,
    isCustom: currentPreset === 'custom',
    unitSuffix: pageSize.unit === 'in' ? '"' : 'mm',
    customDialogOpen,
    setCustomDialogOpen,
    customWidth,
    customHeight,
    customUnit,
    setCustomUnit,
    handlePresetChange: (preset: PresetKey): void => {
      if (preset === 'custom') {
        setCustomWidth(pageSize.width.toString());
        setCustomHeight(pageSize.height.toString());
        setCustomUnit(pageSize.unit);
        setCustomDialogOpen(true);
        return;
      }
      onChange(PAGE_PRESETS[preset]);
    },
    handleCustomDialogSubmit: (): void => {
      const width = Number.parseFloat(customWidth);
      const height = Number.parseFloat(customHeight);
      if (!(Number.isNaN(width) || Number.isNaN(height)) && width > 0 && height > 0) {
        onChange({ width, height, unit: customUnit });
        setCustomDialogOpen(false);
      }
    },
    handleSwapDimensions: (): void => {
      onChange({ ...pageSize, width: pageSize.height, height: pageSize.width });
    },
    handleWidthInput: (e: ChangeEvent<HTMLInputElement>): void =>
      parseAndApply(e.target.value, 'width'),
    handleHeightInput: (e: ChangeEvent<HTMLInputElement>): void =>
      parseAndApply(e.target.value, 'height'),
    handleUnitChange: (unit: 'mm' | 'in'): void => onChange({ ...pageSize, unit }),
    handleCustomWidthInput: (e: ChangeEvent<HTMLInputElement>): void =>
      setCustomWidth(e.target.value),
    handleCustomHeightInput: (e: ChangeEvent<HTMLInputElement>): void =>
      setCustomHeight(e.target.value),
    handleCancelDialog: (): void => setCustomDialogOpen(false),
  };
}
