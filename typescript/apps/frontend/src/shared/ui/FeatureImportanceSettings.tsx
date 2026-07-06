import type { LucideIcon } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { FeatureImportanceRequest } from '@/shared/api/index.ts';
import { cn } from '@/shared/lib/utils/utils.ts';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { Label } from '@/shared/ui/label.tsx';
import { Slider } from '@/shared/ui/slider.tsx';
import type { FeatureDescKey, FeatureLabelKey } from './feature-importance-settings-model.ts';
import {
  DEFAULT_IMPORTANCE_VALUE,
  FEATURE_CONFIGS,
  FEATURE_IMPORTANCE_DEFAULTS,
} from './feature-importance-settings-model.ts';

interface FeatureImportanceSettingsProps {
  readonly values: FeatureImportanceRequest;
  readonly onChange: (values: FeatureImportanceRequest) => void;
  readonly disabled?: boolean;
  readonly showResetButton?: boolean;
  readonly className?: string;
  readonly variant?: 'card' | 'inline';
}

interface FeatureSliderProps {
  readonly featureKey: keyof FeatureImportanceRequest;
  readonly icon: LucideIcon;
  readonly labelKey: FeatureLabelKey;
  readonly descriptionKey: FeatureDescKey;
  readonly value: number;
  readonly disabled: boolean;
  readonly onChange: (key: keyof FeatureImportanceRequest, newValue: number[]) => void;
}

function FeatureSlider({
  featureKey,
  icon: Icon,
  labelKey,
  descriptionKey,
  value,
  disabled,
  onChange,
}: FeatureSliderProps): JSX.Element {
  const { t } = useTranslation(['profiles', 'common']);
  const percentage = value;

  const handleValueChange = (newValue: number[]): void => {
    onChange(featureKey, newValue);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-md bg-primary/10">
            <Icon className="size-4 text-primary" />
          </div>
          <div className="flex flex-col">
            <Label className="font-medium text-sm">{t(labelKey)}</Label>
            <span className="text-muted-foreground text-xs">{t(descriptionKey)}</span>
          </div>
        </div>
        <span className="min-w-12 text-right font-medium text-sm tabular-nums">
          {`${percentage}%`}
        </span>
      </div>
      <Slider
        value={[value]}
        min={0}
        max={100}
        step={5}
        disabled={disabled}
        onValueChange={handleValueChange}
        className="w-full"
      />
    </div>
  );
}

export function FeatureImportanceSettings({
  values,
  onChange,
  disabled = false,
  showResetButton = true,
  className,
  variant = 'card',
}: FeatureImportanceSettingsProps): JSX.Element {
  const { t } = useTranslation(['profiles', 'common']);

  const handleSliderChange = (key: keyof FeatureImportanceRequest, newValue: number[]): void => {
    onChange({
      ...values,
      [key]: newValue[0],
    });
  };

  const handleReset = (): void => {
    onChange(FEATURE_IMPORTANCE_DEFAULTS);
  };

  const content = (
    <div className="space-y-6">
      {FEATURE_CONFIGS.map(({ key, icon, labelKey, descriptionKey }) => (
        <FeatureSlider
          key={key}
          featureKey={key}
          icon={icon}
          labelKey={labelKey as FeatureLabelKey}
          descriptionKey={descriptionKey as FeatureDescKey}
          value={values[key] ?? DEFAULT_IMPORTANCE_VALUE}
          disabled={disabled}
          onChange={handleSliderChange}
        />
      ))}

      {showResetButton ? (
        <div className="flex justify-end pt-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleReset}
            disabled={disabled}
          >
            {t('profiles:featureImportance.resetToDefaults')}
          </Button>
        </div>
      ) : null}
    </div>
  );

  if (variant === 'inline') {
    return <div className={cn('space-y-6', className)}>{content}</div>;
  }

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          {t('profiles:featureImportance.title')}
        </CardTitle>
        <CardDescription>{t('profiles:featureImportance.description')}</CardDescription>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}
