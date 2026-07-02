import { Briefcase } from 'lucide-react';
import type { JSX } from 'react';
import type { Control, ControllerRenderProps } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/shared/ui/form.tsx';
import { Input } from '@/shared/ui/input.tsx';
import { SectionIcon } from '@/shared/ui/section-icon.tsx';
import type { ProfileFormValues } from '../schemas/index.ts';

interface ProfileNameCardProps {
  readonly control: Control<ProfileFormValues>;
}

export function ProfileNameCard({ control }: ProfileNameCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const renderPrefNameField = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormValues, 'pref_name'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('fields.prefName.label')}</FormLabel>
      <FormControl>
        <Input placeholder={t('fields.prefName.placeholder')} {...field} />
      </FormControl>
      <FormMessage />
    </FormItem>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SectionIcon icon={Briefcase} variant="primary" size="sm" />
          {t('fields.prefName.label')}
        </CardTitle>
        <CardDescription>{t('fields.prefName.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <FormField control={control} name="pref_name" render={renderPrefNameField} />
      </CardContent>
    </Card>
  );
}
