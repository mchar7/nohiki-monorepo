import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { Card, CardContent } from '@/shared/ui/index.ts';
import type { OnboardingWelcomeProps } from './Dashboard.types.ts';

function OnboardingWelcome({ displayName, firstName }: OnboardingWelcomeProps): JSX.Element {
  const { t } = useTranslation('dashboard');
  const name: string | null = displayName ?? firstName ?? null;

  return (
    <Card className="border-primary/20 bg-gradient-to-br from-primary/5 to-transparent">
      <CardContent className="p-6">
        <h2 className="font-semibold text-xl tracking-tight">
          {name
            ? t('onboarding.welcome.greeting', { name })
            : t('onboarding.welcome.greetingGeneric')}
        </h2>
        <p className="mt-1 text-muted-foreground text-sm">{t('onboarding.welcome.subtitle')}</p>
      </CardContent>
    </Card>
  );
}

export { OnboardingWelcome };
