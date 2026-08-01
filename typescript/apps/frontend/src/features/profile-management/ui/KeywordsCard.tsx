import { Sparkles } from 'lucide-react';
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
import { TagInput } from '@/shared/ui/TagInput.tsx';
import type { ProfileFormValues } from '../model/index.ts';
import { KEYWORDS_MAX_ITEMS } from '../model/profile.schema.ts';

interface KeywordsCardProps {
  readonly control: Control<ProfileFormValues>;
}

export function KeywordsCard({ control }: KeywordsCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const renderSearchKeywordsField = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormValues, 'search_keywords'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>{t('fields.searchKeywords.label')}</FormLabel>
      <FormControl>
        <TagInput
          value={field.value}
          onChange={field.onChange}
          placeholder={t('fields.searchKeywords.placeholder')}
          maxTags={KEYWORDS_MAX_ITEMS}
        />
      </FormControl>
      <FormDescription>{t('fields.searchKeywords.addHint')}</FormDescription>
      <FormMessage />
    </FormItem>
  );

  const renderDisallowedKeywordsField = ({
    field,
  }: {
    field: ControllerRenderProps<ProfileFormValues, 'disallowed_keywords'>;
  }): JSX.Element => (
    <FormItem>
      <FormLabel>
        {t('fields.disallowedKeywords.label')} <OptionalIndicator />
      </FormLabel>
      <FormControl>
        <TagInput
          value={field.value}
          onChange={field.onChange}
          placeholder={t('fields.disallowedKeywords.placeholder')}
          maxTags={KEYWORDS_MAX_ITEMS}
        />
      </FormControl>
      <FormDescription>{t('fields.disallowedKeywords.description')}</FormDescription>
      <FormMessage />
    </FormItem>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-lg">
          <SectionIcon icon={Sparkles} variant="primary" size="sm" />
          {t('fields.searchKeywords.label')}
        </CardTitle>
        <CardDescription>{t('fields.searchKeywords.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <FormField control={control} name="search_keywords" render={renderSearchKeywordsField} />

        <FormField
          control={control}
          name="disallowed_keywords"
          render={renderDisallowedKeywordsField}
        />
      </CardContent>
    </Card>
  );
}
