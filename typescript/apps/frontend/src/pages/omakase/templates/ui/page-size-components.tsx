import { ArrowRightLeft } from 'lucide-react';

const UNIT_MM = 'mm';
const UNIT_IN = 'in';
const UNIT_INCHES_FULL = 'inches';
const TIMES_SYMBOL = '\u00D7';

import { type ChangeEvent, type JSX, useId } from 'react';
import { Button } from '@/shared/ui/button.tsx';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/ui/dialog.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { Label } from '@/shared/ui/label.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/ui/select.tsx';
import type { PresetKey } from '../lib/page-size.ts';
import type { PageSize } from '../model/index.ts';

interface PresetSelectorProps {
  readonly currentPreset: PresetKey;
  readonly onPresetChange: (preset: PresetKey) => void;
  readonly compact?: boolean;
  readonly t: (key: string) => string;
}

function CompactPresetSelector({
  currentPreset,
  onPresetChange,
  t,
}: Omit<PresetSelectorProps, 'compact'>): JSX.Element {
  return (
    <Select value={currentPreset} onValueChange={onPresetChange}>
      <SelectTrigger className="h-10 w-40">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="letter">
          <span className="flex items-center justify-between gap-4">
            <span>{t('pageSize.preset.letter')}</span>
            <span className="text-muted-foreground text-xs">
              {t('pageSize.preset.letterDimensions')}
            </span>
          </span>
        </SelectItem>
        <SelectItem value="a4">
          <span className="flex items-center justify-between gap-4">
            <span>{t('pageSize.preset.a4')}</span>
            <span className="text-muted-foreground text-xs">
              {t('pageSize.preset.a4Dimensions')}
            </span>
          </span>
        </SelectItem>
        <SelectItem value="custom">{t('pageSize.preset.custom')}</SelectItem>
      </SelectContent>
    </Select>
  );
}

function FullPresetSelector({
  currentPreset,
  onPresetChange,
  t,
}: Omit<PresetSelectorProps, 'compact'>): JSX.Element {
  const presetId = useId();

  return (
    <div className="space-y-2">
      <Label htmlFor={presetId}>{t('pageSize.preset.label')}</Label>
      <Select value={currentPreset} onValueChange={onPresetChange}>
        <SelectTrigger id={presetId} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="letter">
            <div className="flex items-center justify-between gap-4">
              <span>{t('pageSize.preset.letter')}</span>
              <span className="text-muted-foreground text-xs">
                {t('pageSize.preset.letterDimensions')}
              </span>
            </div>
          </SelectItem>
          <SelectItem value="a4">
            <div className="flex items-center justify-between gap-4">
              <span>{t('pageSize.preset.a4')}</span>
              <span className="text-muted-foreground text-xs">
                {t('pageSize.preset.a4Dimensions')}
              </span>
            </div>
          </SelectItem>
          <SelectItem value="custom">
            <span>{t('pageSize.preset.custom')}</span>
          </SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

export function PresetSelector({
  currentPreset,
  onPresetChange,
  compact,
  t,
}: PresetSelectorProps): JSX.Element {
  if (compact) {
    return (
      <CompactPresetSelector currentPreset={currentPreset} onPresetChange={onPresetChange} t={t} />
    );
  }
  return <FullPresetSelector currentPreset={currentPreset} onPresetChange={onPresetChange} t={t} />;
}

interface UnitSelectorProps {
  readonly value: 'mm' | 'in';
  readonly onChange: (unit: 'mm' | 'in') => void;
  readonly compact?: boolean;
  readonly id?: string;
}

function UnitSelector({ value, onChange, compact, id }: UnitSelectorProps): JSX.Element {
  const handleChange = (v: string): void => {
    onChange(v as 'mm' | 'in');
  };

  if (compact) {
    return (
      <Select value={value} onValueChange={handleChange}>
        <SelectTrigger className="h-10 w-17.5">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="mm">{UNIT_MM}</SelectItem>
          <SelectItem value="in">{UNIT_INCHES_FULL}</SelectItem>
        </SelectContent>
      </Select>
    );
  }

  return (
    <Select value={value} onValueChange={handleChange}>
      <SelectTrigger id={id} className="h-9">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="mm">{UNIT_MM}</SelectItem>
        <SelectItem value="in">{UNIT_IN}</SelectItem>
      </SelectContent>
    </Select>
  );
}

interface CompactDimensionInputsProps {
  readonly pageSize: PageSize;
  readonly onWidthChange: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly onHeightChange: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly onUnitChange: (unit: 'mm' | 'in') => void;
  readonly onSwap: () => void;
  readonly t: (key: string) => string;
}

export function CompactDimensionInputs({
  pageSize,
  onWidthChange,
  onHeightChange,
  onUnitChange,
  onSwap,
  t,
}: CompactDimensionInputsProps): JSX.Element {
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-10 items-center gap-2 rounded-md border border-input bg-background px-3">
        <input
          type="number"
          step="0.1"
          min="0.1"
          value={pageSize.width}
          onChange={onWidthChange}
          className="w-14 bg-transparent text-center text-sm outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        />
        <span className="text-muted-foreground">{TIMES_SYMBOL}</span>
        <input
          type="number"
          step="0.1"
          min="0.1"
          value={pageSize.height}
          onChange={onHeightChange}
          className="w-14 bg-transparent text-center text-sm outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        />
      </div>
      <UnitSelector value={pageSize.unit} onChange={onUnitChange} compact={true} />
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={onSwap}
        title={t('pageSize.swap')}
        aria-label={t('pageSize.swap')}
        className="size-10"
      >
        <ArrowRightLeft className="size-4" />
      </Button>
    </div>
  );
}

interface CustomSizeDialogProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly customWidth: string;
  readonly customHeight: string;
  readonly customUnit: 'mm' | 'in';
  readonly onWidthChange: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly onHeightChange: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly onUnitChange: (unit: 'mm' | 'in') => void;
  readonly onSubmit: () => void;
  readonly onCancel: () => void;
  readonly t: (key: string) => string;
}

export function CustomSizeDialog({
  open,
  onOpenChange,
  customWidth,
  customHeight,
  customUnit,
  onWidthChange,
  onHeightChange,
  onUnitChange,
  onSubmit,
  onCancel,
  t,
}: CustomSizeDialogProps): JSX.Element {
  const customWidthId = useId();
  const customHeightId = useId();
  const customUnitId = useId();

  const handleUnitChange = (v: string): void => {
    onUnitChange(v as 'mm' | 'in');
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('pageSize.customDialog.title')}</DialogTitle>
          <DialogDescription>{t('pageSize.customDialog.description')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor={customWidthId}>{t('pageSize.width')}</Label>
              <Input
                id={customWidthId}
                type="number"
                step="0.1"
                min="0.1"
                value={customWidth}
                onChange={onWidthChange}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={customHeightId}>{t('pageSize.height')}</Label>
              <Input
                id={customHeightId}
                type="number"
                step="0.1"
                min="0.1"
                value={customHeight}
                onChange={onHeightChange}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor={customUnitId}>{t('pageSize.unit')}</Label>
            <Select value={customUnit} onValueChange={handleUnitChange}>
              <SelectTrigger id={customUnitId}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="mm">{t('pageSize.units.millimeters')}</SelectItem>
                <SelectItem value="in">{t('pageSize.units.inches')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {t('actions.cancel')}
          </Button>
          <Button onClick={onSubmit}>{t('actions.apply')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface FullDimensionEditorProps {
  readonly pageSize: PageSize;
  readonly isCustom: boolean;
  readonly onWidthChange: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly onHeightChange: (e: ChangeEvent<HTMLInputElement>) => void;
  readonly onUnitChange: (unit: 'mm' | 'in') => void;
  readonly onSwap: () => void;
  readonly t: (key: string) => string;
}

export function FullDimensionEditor({
  pageSize,
  isCustom,
  onWidthChange,
  onHeightChange,
  onUnitChange,
  onSwap,
  t,
}: FullDimensionEditorProps): JSX.Element | null {
  const widthId = useId();
  const heightId = useId();
  const unitId = useId();

  if (!isCustom) {
    return null;
  }

  return (
    <div className="space-y-4 rounded-lg border bg-muted/30 p-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor={widthId} className="text-sm">
            {t('pageSize.width')}
          </Label>
          <Input
            id={widthId}
            type="number"
            step="0.1"
            min="0.1"
            value={pageSize.width}
            onChange={onWidthChange}
            className="h-9"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={heightId} className="text-sm">
            {t('pageSize.height')}
          </Label>
          <Input
            id={heightId}
            type="number"
            step="0.1"
            min="0.1"
            value={pageSize.height}
            onChange={onHeightChange}
            className="h-9"
          />
        </div>
      </div>
      <div className="flex items-end gap-3">
        <div className="flex-1 space-y-2">
          <Label htmlFor={unitId} className="text-sm">
            {t('pageSize.unit')}
          </Label>
          <UnitSelector value={pageSize.unit} onChange={onUnitChange} id={unitId} />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onSwap}
          title={t('pageSize.swap')}
          className="h-9 px-3"
        >
          <ArrowRightLeft className="size-4" />
        </Button>
      </div>
    </div>
  );
}
