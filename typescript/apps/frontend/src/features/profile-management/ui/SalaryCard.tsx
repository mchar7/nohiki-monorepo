import { DollarSign } from 'lucide-react';
import type { JSX } from 'react';
import type { Control, ControllerRenderProps } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/shared/ui/form.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { SectionIcon } from '@/shared/ui/section-icon.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/ui/select.tsx';
import type { ProfileFormValues } from '../schemas/index.ts';

const CURRENCY_OPTIONS = ['USD', 'CAD', 'EUR', 'GBP'] as const;
const FREQUENCY_OPTIONS = ['HOURLY', 'DAILY', 'WEEKLY', 'BIWEEKLY', 'MONTHLY', 'ANNUALLY'] as const;

const CENTS_PER_DOLLAR: number = 100;

interface SalaryCardProps {
  readonly control: Control<ProfileFormValues>;
}

function SalaryCard({ control }: SalaryCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SectionIcon icon={DollarSign} variant="primary" size="sm" />
          {t('fields.salary.label')}
        </CardTitle>
        <CardDescription>{t('fields.salary.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            control={control}
            name="salary_preference.min_salary.currency"
            render={renderCurrencyField}
          />
          <FormField
            control={control}
            name="salary_preference.preferred_frequency"
            render={renderFrequencyField}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField
            control={control}
            name="salary_preference.min_salary.minor_units"
            render={renderMinorUnitsField}
          />
          <FormField
            control={control}
            name="salary_preference.target_salary.minor_units"
            render={renderTargetUnitsField}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function renderCurrencyField({
  field,
}: {
  field: ControllerRenderProps<ProfileFormValues, 'salary_preference.min_salary.currency'>;
}): JSX.Element {
  return <CurrencySelect value={field.value} onChange={field.onChange} />;
}

function CurrencySelect({
  value,
  onChange,
}: {
  readonly value: string;
  readonly onChange: (value: string) => void;
}): JSX.Element {
  const { t } = useTranslation('profiles');

  return (
    <FormItem>
      <FormLabel>{t('fields.salary.currencyLabel')}</FormLabel>
      <Select onValueChange={onChange} value={value}>
        <FormControl>
          <SelectTrigger className="w-full">
            <SelectValue placeholder={t('fields.salary.currencyPlaceholder')} />
          </SelectTrigger>
        </FormControl>
        <SelectContent>
          {CURRENCY_OPTIONS.map((currency) => (
            <SelectItem key={currency} value={currency}>
              {t(`fields.salary.currencyOptions.${currency}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <FormMessage />
    </FormItem>
  );
}

function renderFrequencyField({
  field,
}: {
  field: ControllerRenderProps<ProfileFormValues, 'salary_preference.preferred_frequency'>;
}): JSX.Element {
  return <FrequencySelect value={field.value ?? ''} onChange={field.onChange} />;
}

function FrequencySelect({
  value,
  onChange,
}: {
  readonly value: string;
  readonly onChange: (value: string) => void;
}): JSX.Element {
  const { t } = useTranslation('profiles');

  return (
    <FormItem>
      <FormLabel>{t('fields.salary.frequencyLabel')}</FormLabel>
      <Select onValueChange={onChange} value={value}>
        <FormControl>
          <SelectTrigger className="w-full">
            <SelectValue placeholder={t('fields.salary.frequencyPlaceholder')} />
          </SelectTrigger>
        </FormControl>
        <SelectContent>
          {FREQUENCY_OPTIONS.map((freq) => (
            <SelectItem key={freq} value={freq}>
              {t(`fields.salary.frequencyOptions.${freq}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <FormMessage />
    </FormItem>
  );
}

function renderMinorUnitsField({
  field,
}: {
  field: ControllerRenderProps<ProfileFormValues, 'salary_preference.min_salary.minor_units'>;
}): JSX.Element {
  return <SalaryAmountInput value={field.value} onChange={field.onChange} fieldKey="min" />;
}

function renderTargetUnitsField({
  field,
}: {
  field: ControllerRenderProps<ProfileFormValues, 'salary_preference.target_salary.minor_units'>;
}): JSX.Element {
  return <SalaryAmountInput value={field.value} onChange={field.onChange} fieldKey="target" />;
}

function SalaryAmountInput({
  value,
  onChange,
  fieldKey,
}: {
  readonly value: number;
  readonly onChange: (value: number) => void;
  readonly fieldKey: 'min' | 'target';
}): JSX.Element {
  const { t } = useTranslation('profiles');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const dollars = Number.parseFloat(e.target.value) || 0;
    onChange(Math.round(dollars * CENTS_PER_DOLLAR));
  };

  const labelKey = fieldKey === 'min' ? 'fields.salary.minLabel' : 'fields.salary.targetLabel';
  const placeholderKey =
    fieldKey === 'min' ? 'fields.salary.minPlaceholder' : 'fields.salary.targetPlaceholder';

  return (
    <FormItem>
      <FormLabel>{t(labelKey)}</FormLabel>
      <FormControl>
        <Input
          type="number"
          min={0}
          value={value === 0 ? '' : value / CENTS_PER_DOLLAR}
          onChange={handleChange}
          placeholder={t(placeholderKey)}
        />
      </FormControl>
      <FormMessage />
    </FormItem>
  );
}

export { SalaryCard };
