import { Home } from 'lucide-react';
import type { JSX } from 'react';
import type { Control, ControllerRenderProps } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import type { ProfileResponse } from '@/shared/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { Checkbox } from '@/shared/ui/checkbox.tsx';
import { FormField, FormItem, FormMessage } from '@/shared/ui/form.tsx';
import { Label } from '@/shared/ui/label.tsx';
import { SectionIcon } from '@/shared/ui/section-icon.tsx';
import type { ProfileFormValues } from '../model/index.ts';

type WorkArrangementKey = ProfileResponse['work_arrangements'][number];

const WORK_ARRANGEMENT_OPTIONS: readonly WorkArrangementKey[] = ['ON_SITE', 'HYBRID', 'REMOTE'];

interface WorkArrangementsCardProps {
  readonly control: Control<ProfileFormValues>;
}

function WorkArrangementsCard({ control }: WorkArrangementsCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const renderWorkArrangementsField = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormValues, 'work_arrangements'>;
  }): JSX.Element => (
    <FormItem>
      <WorkArrangementsList value={field.value} onChange={field.onChange} />
      <FormMessage />
    </FormItem>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SectionIcon icon={Home} variant="primary" size="sm" />
          {t('fields.workArrangements.label')}
        </CardTitle>
        <CardDescription>{t('fields.workArrangements.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <FormField
          control={control}
          name="work_arrangements"
          render={renderWorkArrangementsField}
        />
      </CardContent>
    </Card>
  );
}

interface WorkArrangementsListProps {
  readonly value: string[];
  readonly onChange: (value: string[]) => void;
}

function WorkArrangementsList({ value, onChange }: WorkArrangementsListProps): JSX.Element {
  const handleCheckedChange = (option: string, checked: boolean): void => {
    onChange(checked ? [...value, option] : value.filter((v) => v !== option));
  };

  return (
    <div className="grid grid-cols-2 gap-4">
      {WORK_ARRANGEMENT_OPTIONS.map((option) => (
        <WorkArrangementOptionItem
          key={option}
          option={option}
          checked={value.includes(option)}
          onCheckedChange={handleCheckedChange}
        />
      ))}
    </div>
  );
}

interface WorkArrangementOptionItemProps {
  readonly option: WorkArrangementKey;
  readonly checked: boolean;
  readonly onCheckedChange: (option: string, checked: boolean) => void;
}

function WorkArrangementOptionItem({
  option,
  checked,
  onCheckedChange,
}: WorkArrangementOptionItemProps): JSX.Element {
  const { t } = useTranslation('profiles');
  const id = `work-${option}`;

  const handleCheckedChange = (isChecked: boolean): void => {
    onCheckedChange(option, isChecked);
  };

  const labelMap = {
    ON_SITE: t('fields.workArrangements.options.ON_SITE'),
    HYBRID: t('fields.workArrangements.options.HYBRID'),
    REMOTE: t('fields.workArrangements.options.REMOTE'),
  } as const;

  return (
    <div className="flex items-center space-x-3 rounded-lg border p-4 transition-colors hover:bg-accent/50">
      <Checkbox id={id} checked={checked} onCheckedChange={handleCheckedChange} />
      <Label htmlFor={id} className="flex-1 cursor-pointer font-normal">
        {labelMap[option]}
      </Label>
    </div>
  );
}

export { WorkArrangementsCard };
