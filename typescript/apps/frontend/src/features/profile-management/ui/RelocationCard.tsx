import { Globe } from 'lucide-react';
import type { JSX } from 'react';
import type { Control, ControllerRenderProps } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { FormControl, FormDescription, FormField, FormItem, FormLabel } from '@/shared/ui/form.tsx';
import { SectionIcon } from '@/shared/ui/section-icon.tsx';
import { Switch } from '@/shared/ui/switch.tsx';
import type { ProfileFormValues } from '../model/index.ts';

interface RelocationCardProps {
  readonly control: Control<ProfileFormValues>;
}

export function RelocationCard({ control }: RelocationCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const renderRelocationField = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormValues, 'open_to_relocation'>;
  }): JSX.Element => (
    <FormItem className="flex flex-row items-center justify-between rounded-lg border p-4 transition-colors hover:bg-accent/50">
      <div className="space-y-0.5">
        <FormLabel className="cursor-pointer text-base">{t('fields.relocation.label')}</FormLabel>
        <FormDescription>{t('fields.relocation.hint')}</FormDescription>
      </div>
      <FormControl>
        <Switch checked={field.value} onCheckedChange={field.onChange} />
      </FormControl>
    </FormItem>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SectionIcon icon={Globe} variant="primary" size="sm" />
          {t('fields.relocation.title')}
        </CardTitle>
        <CardDescription>{t('fields.relocation.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <FormField control={control} name="open_to_relocation" render={renderRelocationField} />
      </CardContent>
    </Card>
  );
}
