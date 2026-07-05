import { Link } from '@tanstack/react-router';
import { BookOpen, Bug, ExternalLink, Scale, Sparkles } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { GitHubIcon } from '@/shared/ui/icons.tsx';
import { Separator } from '@/shared/ui/separator.tsx';

const APP_VERSION: string = import.meta.env.VITE_APP_VERSION || '0.1.0';
const CURRENT_YEAR: number = new Date().getFullYear();

function AboutSection(): JSX.Element {
  const { t } = useTranslation('settings');

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>{t('about.title')}</CardTitle>
            <CardDescription className="mt-1">
              {t('about.version', { version: APP_VERSION })}
            </CardDescription>
          </div>
          <Badge variant="outline" className="text-xs">
            {`v${APP_VERSION}`}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <p className="text-muted-foreground text-sm">{t('about.description')}</p>

        <Separator />

        <div className="space-y-3">
          <h4 className="font-medium text-sm">{t('sections.about')}</h4>
          <div className="grid grid-cols-2 gap-2">
            <ExternalLinkButton
              icon={BookOpen}
              label={t('about.links.documentation')}
              href="https://docs.nohiki.dev"
            />
            <ExternalLinkButton
              icon={GitHubIcon}
              label={t('about.links.github')}
              href="https://github.com/nohiki"
            />
            <ExternalLinkButton
              icon={Bug}
              label={t('about.links.reportBug')}
              href="https://github.com/nohiki/issues/new?template=bug_report.md"
            />
            <ExternalLinkButton
              icon={Sparkles}
              label={t('about.links.requestFeature')}
              href="https://github.com/nohiki/issues/new?template=feature_request.md"
            />
          </div>
        </div>

        <Separator />

        <div className="space-y-3">
          <h4 className="font-medium text-sm">{t('sections.privacy')}</h4>
          <div className="grid grid-cols-3 gap-2">
            <ExternalLinkButton
              icon={ExternalLink}
              label={t('about.legal.terms')}
              href="https://www.nohiki.com/terms"
            />
            <ExternalLinkButton
              icon={ExternalLink}
              label={t('about.legal.privacy')}
              href="https://www.nohiki.com/privacy"
            />
            <InternalLinkButton icon={Scale} label={t('about.legal.licenses')} to="/licenses" />
          </div>
        </div>

        <p className="text-muted-foreground text-xs">
          {t('about.copyright', { year: CURRENT_YEAR })}
        </p>
      </CardContent>
    </Card>
  );
}

interface ExternalLinkButtonProps {
  readonly icon: React.ComponentType<{ className?: string }>;
  readonly label: string;
  readonly href: string;
}

function ExternalLinkButton({ icon: Icon, label, href }: ExternalLinkButtonProps): JSX.Element {
  return (
    <Button variant="outline" size="sm" className="justify-start" asChild={true}>
      <a href={href} target="_blank" rel="noopener noreferrer">
        <Icon className="mr-2 size-4" />
        {label}
        <ExternalLink className="ml-auto size-3 opacity-50" />
      </a>
    </Button>
  );
}

interface InternalLinkButtonProps {
  readonly icon: typeof Scale;
  readonly label: string;
  readonly to: string;
}

function InternalLinkButton({ icon: Icon, label, to }: InternalLinkButtonProps): JSX.Element {
  return (
    <Button variant="outline" size="sm" className="justify-start" asChild={true}>
      <Link to={to}>
        <Icon className="mr-2 size-4" />
        {label}
      </Link>
    </Button>
  );
}

export { AboutSection };
