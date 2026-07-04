import { Link } from '@tanstack/react-router';
import { ArrowRight, Target, X } from 'lucide-react';
import { type JSX, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ROUTE_PATHS } from '@/shared/config';
import { Button, Card, CardContent } from '@/shared/ui/index.ts';

interface DashboardNewMatchesBannerProps {
  readonly newMatchCount: number;
}

export function DashboardNewMatchesBanner({
  newMatchCount,
}: DashboardNewMatchesBannerProps): JSX.Element | null {
  const { t } = useTranslation('dashboard');
  const [dismissed, setDismissed] = useState(false);

  if (newMatchCount === 0 || dismissed) {
    return null;
  }

  return (
    <Card className="border-primary/20 bg-primary/5" role="alert" aria-live="polite">
      <CardContent className="flex items-center gap-3 p-4">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
          <Target className="size-4 text-primary" />
        </div>

        <p className="min-w-0 flex-1 font-medium text-sm">
          {t('banner.newMatches.message', { count: newMatchCount })}
        </p>

        <Button variant="ghost" size="sm" asChild={true}>
          <Link to={ROUTE_PATHS.JOBS.MATCHES} className="gap-1 text-primary">
            {t('banner.newMatches.viewMatches')}
            <ArrowRight className="size-4" />
          </Link>
        </Button>

        <Button
          variant="ghost"
          size="icon"
          className="size-7 shrink-0 text-muted-foreground hover:text-foreground"
          onClick={() => setDismissed(true)}
          aria-label={t('banner.newMatches.dismiss')}
        >
          <X className="size-4" />
        </Button>
      </CardContent>
    </Card>
  );
}
