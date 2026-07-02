import type { TFunction } from 'i18next';
import { Info, SlidersHorizontal } from 'lucide-react';
import type { JSX } from 'react';
import type { Control, ControllerRenderProps } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/shared/ui/form.tsx';
import { OptionalIndicator } from '@/shared/ui/optional-indicator.tsx';
import { SectionIcon } from '@/shared/ui/section-icon.tsx';
import { Slider } from '@/shared/ui/slider.tsx';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/ui/tooltip.tsx';
import type { ProfileFormValues } from '../schemas/index.ts';

type TranslationFn = TFunction<'profiles'>;

const THRESHOLD_EXCELLENT: number = 85;
const THRESHOLD_GOOD: number = 70;
const THRESHOLD_DECENT: number = 60;

function getThresholdDescription(value: number, t: TranslationFn): string {
  if (value >= THRESHOLD_EXCELLENT) {
    return t('fields.notificationThreshold.descriptions.excellent');
  }
  if (value >= THRESHOLD_GOOD) {
    return t('fields.notificationThreshold.descriptions.good');
  }
  if (value >= THRESHOLD_DECENT) {
    return t('fields.notificationThreshold.descriptions.decent');
  }
  return t('fields.notificationThreshold.descriptions.many');
}

interface ThresholdsCardProps {
  readonly control: Control<ProfileFormValues>;
}

function ThresholdsCard({ control }: ThresholdsCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SectionIcon icon={SlidersHorizontal} variant="primary" size="sm" />
          {t('fields.notificationThreshold.label')}
        </CardTitle>
        <CardDescription>{t('fields.notificationThreshold.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-8">
        <NotificationThresholdField control={control} />
        <AutoTailorThresholdField control={control} />
      </CardContent>
    </Card>
  );
}

interface NotificationThresholdInputProps {
  readonly field: ControllerRenderProps<ProfileFormValues, 'notification_threshold'>;
}

function NotificationThresholdInput({ field }: NotificationThresholdInputProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const handleValueChange = (v: number[]): void => {
    field.onChange(v[0]);
  };

  return (
    <FormItem>
      <div className="flex items-center justify-between">
        <FormLabel className="inline-flex items-center gap-1.5">
          {t('fields.notificationThreshold.label')}
          <Tooltip>
            <TooltipTrigger asChild={true}>
              <Info className="size-3.5 text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent>
              <p>{t('fields.notificationThreshold.tooltip')}</p>
            </TooltipContent>
          </Tooltip>
        </FormLabel>
        <span className="font-medium text-sm tabular-nums">{`${field.value} / 100`}</span>
      </div>
      <FormControl>
        <Slider
          value={[field.value]}
          onValueChange={handleValueChange}
          min={0}
          max={100}
          step={5}
        />
      </FormControl>
      <FormDescription>
        {t('fields.notificationThreshold.hint', { threshold: field.value })}
      </FormDescription>
      <p className="text-muted-foreground text-xs">{getThresholdDescription(field.value, t)}</p>
      <FormMessage />
    </FormItem>
  );
}

function renderNotificationThresholdField({
  field,
}: {
  field: ControllerRenderProps<ProfileFormValues, 'notification_threshold'>;
}): JSX.Element {
  return <NotificationThresholdInput field={field} />;
}

function NotificationThresholdField({
  control,
}: {
  readonly control: Control<ProfileFormValues>;
}): JSX.Element {
  return (
    <FormField
      control={control}
      name="notification_threshold"
      render={renderNotificationThresholdField}
    />
  );
}

interface AutoTailorThresholdInputProps {
  readonly field: ControllerRenderProps<ProfileFormValues, 'auto_tailor_threshold'>;
}

function AutoTailorThresholdInput({ field }: AutoTailorThresholdInputProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const handleValueChange = (v: number[]): void => {
    const [val] = v;
    field.onChange(val !== undefined && val > 0 ? val : null);
  };

  return (
    <FormItem>
      <div className="flex items-center justify-between">
        <FormLabel>
          {t('fields.autoTailorThreshold.label')} <OptionalIndicator />
        </FormLabel>
        <span className="font-medium text-sm tabular-nums">
          {field.value === null ? '-' : `${field.value} / 100`}
        </span>
      </div>
      <FormControl>
        <Slider
          value={[field.value ?? 0]}
          onValueChange={handleValueChange}
          min={0}
          max={100}
          step={5}
        />
      </FormControl>
      <FormDescription>{t('fields.autoTailorThreshold.hint')}</FormDescription>
      <FormMessage />
    </FormItem>
  );
}

function renderAutoTailorThresholdField({
  field,
}: {
  field: ControllerRenderProps<ProfileFormValues, 'auto_tailor_threshold'>;
}): JSX.Element {
  return <AutoTailorThresholdInput field={field} />;
}

function AutoTailorThresholdField({
  control,
}: {
  readonly control: Control<ProfileFormValues>;
}): JSX.Element {
  return (
    <FormField
      control={control}
      name="auto_tailor_threshold"
      render={renderAutoTailorThresholdField}
    />
  );
}

export { ThresholdsCard };
