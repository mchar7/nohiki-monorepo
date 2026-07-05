import { Link } from '@tanstack/react-router';
import { FileCode2 } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { TemplateFamilyResponse } from '@/shared/api';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/shared/ui/card';

interface TemplateCardProps {
  template: TemplateFamilyResponse;
}

export function TemplateCard({ template }: TemplateCardProps): JSX.Element {
  const { t } = useTranslation(['documents', 'common']);

  const latestVersion = template.latest_version?.version ?? '1.0.0';
  const displayName = template.display_name || t('common:unavailable');

  return (
    <Card className="flex h-full flex-col overflow-hidden transition-all hover:shadow-md">
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
        <div className="space-y-1">
          <CardTitle className="text-xl">{displayName}</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="capitalize">
              {template.namespace.replace(/_/gu, ' ')}
            </Badge>
            <span className="text-muted-foreground text-xs">
              {t('templates.card.version', { version: latestVersion })}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center justify-center rounded-md border bg-muted/50 p-2">
          <FileCode2 className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
        </div>
      </CardHeader>
      <CardContent className="flex-1 pt-4">
        <CardDescription className="line-clamp-3">
          {template.description || t('templates.gallery.emptyDescription')}
        </CardDescription>
      </CardContent>
      <CardFooter className="flex items-center gap-2 border-t pt-4">
        <Button asChild={true} variant="default" className="flex-1">
          <Link
            to="/documents/generate"
            search={{ templateId: template.id }}
            aria-label={`${t('templates.card.useTemplate')} ${displayName}`}
          >
            {t('templates.card.useTemplate')}
          </Link>
        </Button>
        <Button asChild={true} variant="outline" className="flex-1">
          <Link
            to="/documents/templates/studio"
            aria-label={`${t('templates.card.customize')} ${displayName}`}
          >
            {t('templates.card.customize')}
          </Link>
        </Button>
      </CardFooter>
    </Card>
  );
}
