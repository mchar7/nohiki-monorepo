import { GraduationCap, Minus, Plus } from 'lucide-react';
import type { JSX } from 'react';
import type { Control, ControllerRenderProps } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import type { ProfileResponse } from '@/shared/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { Checkbox } from '@/shared/ui/checkbox.tsx';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/shared/ui/form.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { Label } from '@/shared/ui/label.tsx';
import { SectionIcon } from '@/shared/ui/section-icon.tsx';
import type { ProfileFormValues } from '../model/index.ts';

type ExperiencePref = NonNullable<ProfileResponse['experience_preference']>;
type SeniorityLevelKey = NonNullable<ExperiencePref['seniority_levels']>[number];

const SENIORITY_LEVEL_OPTIONS: readonly SeniorityLevelKey[] = [
  'INTERN',
  'ENTRY',
  'MID',
  'SENIOR',
  'STAFF',
  'MANAGER',
  'DIRECTOR',
  'VP',
  'EXECUTIVE',
];

const MAX_EXPERIENCE_YEARS: number = 50;

interface ExperienceCardProps {
  readonly control: Control<ProfileFormValues>;
}

function ExperienceCard({ control }: ExperienceCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const renderExperienceYearsField = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormValues, 'experience_preference.experience_years'>;
  }): JSX.Element => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
      field.onChange(Number.parseInt(e.target.value, 10) || 0);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      e.preventDefault();
      adjustExperienceYears(e.key === 'ArrowUp' ? 1 : -1);
    };

    const adjustExperienceYears = (amount: number): void => {
      field.onChange(Math.min(MAX_EXPERIENCE_YEARS, Math.max(0, field.value + amount)));
    };

    const decrementExperienceYears = (): void => {
      adjustExperienceYears(-1);
    };

    const incrementExperienceYears = (): void => {
      adjustExperienceYears(1);
    };

    return (
      <FormItem>
        <FormLabel>{t('fields.experience.yearsLabel')}</FormLabel>
        <div className="flex w-full max-w-xs overflow-hidden rounded-md border border-input bg-background shadow-sm transition-[color,box-shadow] focus-within:border-ring focus-within:ring-1 focus-within:ring-ring has-aria-invalid:border-destructive has-aria-invalid:ring-destructive/20 dark:bg-input/30 dark:has-aria-invalid:ring-destructive/40">
          <button
            type="button"
            className="flex size-11 shrink-0 items-center justify-center border-input border-r text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
            aria-label={t('fields.experience.decreaseYears')}
            disabled={field.disabled || field.value <= 0}
            onClick={decrementExperienceYears}
          >
            <Minus className="size-4" aria-hidden="true" />
          </button>
          <FormControl>
            <Input
              ref={field.ref}
              name={field.name}
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_EXPERIENCE_YEARS}
              step={1}
              value={field.value}
              disabled={field.disabled}
              onBlur={field.onBlur}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              className="h-11 min-w-0 flex-1 rounded-none border-0 bg-transparent text-center text-base tabular-nums shadow-none [appearance:textfield] focus-visible:ring-0 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
          </FormControl>
          <button
            type="button"
            className="flex size-11 shrink-0 items-center justify-center border-input border-l text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
            aria-label={t('fields.experience.increaseYears')}
            disabled={field.disabled || field.value >= MAX_EXPERIENCE_YEARS}
            onClick={incrementExperienceYears}
          >
            <Plus className="size-4" aria-hidden="true" />
          </button>
        </div>
        <FormMessage />
      </FormItem>
    );
  };

  const renderSeniorityLevelsField = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormValues, 'experience_preference.seniority_levels'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('fields.experience.seniorityLabel')}</FormLabel>
      <SeniorityLevelsList value={field.value} onChange={field.onChange} />
      <FormMessage />
    </FormItem>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SectionIcon icon={GraduationCap} variant="primary" size="sm" />
          {t('fields.experience.label')}
        </CardTitle>
        <CardDescription>{t('fields.experience.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <FormField
          control={control}
          name="experience_preference.experience_years"
          render={renderExperienceYearsField}
        />
        <FormField
          control={control}
          name="experience_preference.seniority_levels"
          render={renderSeniorityLevelsField}
        />
      </CardContent>
    </Card>
  );
}

interface SeniorityLevelsListProps {
  readonly value: string[];
  readonly onChange: (value: string[]) => void;
}

function SeniorityLevelsList({ value, onChange }: SeniorityLevelsListProps): JSX.Element {
  const handleCheckedChange = (option: string, checked: boolean): void => {
    onChange(checked ? [...value, option] : value.filter((v) => v !== option));
  };

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
      {SENIORITY_LEVEL_OPTIONS.map((option) => (
        <SeniorityLevelOptionItem
          key={option}
          option={option}
          checked={value.includes(option)}
          onCheckedChange={handleCheckedChange}
        />
      ))}
    </div>
  );
}

interface SeniorityLevelOptionItemProps {
  readonly option: SeniorityLevelKey;
  readonly checked: boolean;
  readonly onCheckedChange: (option: string, checked: boolean) => void;
}

function SeniorityLevelOptionItem({
  option,
  checked,
  onCheckedChange,
}: SeniorityLevelOptionItemProps): JSX.Element {
  const { t } = useTranslation('profiles');
  const id = `seniority-${option}`;

  const handleCheckedChange = (isChecked: boolean): void => {
    onCheckedChange(option, isChecked);
  };

  return (
    <div className="flex items-center space-x-3 rounded-lg border p-4 transition-colors hover:bg-accent/50">
      <Checkbox id={id} checked={checked} onCheckedChange={handleCheckedChange} />
      <Label htmlFor={id} className="flex-1 cursor-pointer font-normal">
        {t(`fields.experience.seniorityOptions.${option}`)}
      </Label>
    </div>
  );
}

export { ExperienceCard };
