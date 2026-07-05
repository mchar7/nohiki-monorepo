import { AlertTriangle } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { useDocumentTitle } from '@/shared/lib/index.ts';
import { Alert, AlertDescription, AlertTitle } from '@/shared/ui/alert.tsx';
import { Badge } from '@/shared/ui/badge.tsx';
import { PageHeader } from '@/shared/ui/index.ts';
import { Separator } from '@/shared/ui/separator.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';
import { AboutSection } from './AboutSection.tsx';
import { ApiEndpointSettings } from './ApiEndpointSettings.tsx';
import { DeveloperInfo } from './DeveloperInfo.tsx';
import { ThemeSettings } from './ThemeSettings.tsx';

function Settings(): JSX.Element {
  const { t } = useTranslation('settings');
  const isDevelopment = import.meta.env.DEV;

  useDocumentTitle(t('title'));

  return (
    <PageLayout contentWidth="narrow" className="space-y-8">
      <PageHeader
        title={t('title')}
        description={t('subtitle')}
        backTo={ROUTE_PATHS.ACCOUNT.SETTINGS}
        preferHistory={true}
      />
      {/* Appearance Settings */}
      <section>
        <SectionHeader title={t('appearance.title')} description={t('appearance.description')} />
        <ThemeSettings />
      </section>

      <Separator />

      {/* About Section */}
      <section>
        <SectionHeader title={t('sections.about')} description={t('about.sectionDescription')} />
        <AboutSection />
      </section>

      {/* Developer-only sections */}
      {isDevelopment ? (
        <>
          <Separator />

          <Alert variant="warning">
            <AlertTriangle className="size-4" />
            <AlertTitle className="flex items-center gap-2">
              {t('developer.devMode')}
              <Badge variant="outline" className="border-warning/50 text-warning text-xs">
                {t('developer.devOnly')}
              </Badge>
            </AlertTitle>
            <AlertDescription>{t('developer.devModeDescription')}</AlertDescription>
          </Alert>

          <section>
            <SectionHeader title={t('api.title')} description={t('api.description')} />
            <ApiEndpointSettings />
          </section>

          <Separator />

          <section>
            <SectionHeader title={t('developer.title')} description={t('developer.description')} />
            <DeveloperInfo />
          </section>
        </>
      ) : null}
    </PageLayout>
  );
}

interface SectionHeaderProps {
  readonly title: string;
  readonly description: string;
}

function SectionHeader({ title, description }: SectionHeaderProps): JSX.Element {
  return (
    <div className="mb-4">
      <h2 className="font-semibold text-lg">{title}</h2>
      <p className="text-muted-foreground text-sm">{description}</p>
    </div>
  );
}

export { Settings };
