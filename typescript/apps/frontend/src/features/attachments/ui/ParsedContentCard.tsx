import { Sparkles } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';

function ParsedContentCard(): JSX.Element {
  const { t } = useTranslation('attachments');

  return (
    <Card className="opacity-60">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />
          {t('parsedContent.title')}
        </CardTitle>
        <CardDescription>{t('parsedContent.description')}</CardDescription>
      </CardHeader>
      <CardContent />
    </Card>
  );
}

export { ParsedContentCard };
