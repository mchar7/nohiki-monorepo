import { Briefcase } from 'lucide-react';
import type { JSX } from 'react';
import type { ControllerRenderProps } from 'react-hook-form';
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
import { SectionIcon } from '@/shared/ui/section-icon.tsx';
import { SkillInput } from '@/shared/ui/skill-input/SkillInput.tsx';
import type { ProfileFormValues } from '../schemas/index.ts';
import { KEYWORDS_MAX_ITEMS } from '../schemas/index.ts';
import type { SkillsCardProps } from './SkillsCard.types.ts';

function SkillsCard({ control }: SkillsCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const renderUserSkillsField = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormValues, 'user_skills'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('fields.userSkills.label')}</FormLabel>
      <FormControl>
        <SkillInput
          value={field.value}
          onChange={field.onChange}
          placeholder={t('fields.userSkills.placeholder')}
          maxSkills={KEYWORDS_MAX_ITEMS}
        />
      </FormControl>
      <FormDescription>{t('fields.userSkills.description')}</FormDescription>
      <FormMessage />
    </FormItem>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SectionIcon icon={Briefcase} variant="primary" size="sm" />
          {t('sections.userSkills.title')}
        </CardTitle>
        <CardDescription>{t('sections.userSkills.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <FormField control={control} name="user_skills" render={renderUserSkillsField} />
      </CardContent>
    </Card>
  );
}

export { SkillsCard };
