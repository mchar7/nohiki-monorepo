import { Link } from '@tanstack/react-router';
import { ArrowRight, BookOpen, Lightbulb } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { ROUTE_PATHS } from '@/shared/config';
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/shared/ui/index.ts';
import type { CommonMissingSkillsWidgetProps } from './Dashboard.types.ts';

/**
 * Fallback widget for skill gap analysis.
 *
 * Per-skill gap data isn't available from the API (score_breakdown contains scoring
 * dimensions like maxsim/skillsSemantic, not individual skill names). This widget
 * renders contextual guidance instead:
 * - No skills on profile → CTA to add skills
 * - Has skills → "coming soon" teaser with jobs CTA
 */
function CommonMissingSkillsWidget({
  hasSkills,
  profileId,
}: CommonMissingSkillsWidgetProps): JSX.Element {
  if (!hasSkills) {
    return <ImproveMatchesCard profileId={profileId} />;
  }

  return <ComingSoonCard />;
}

interface ImproveMatchesCardProps {
  readonly profileId?: string;
}

function ImproveMatchesCard({ profileId }: ImproveMatchesCardProps): JSX.Element {
  const { t } = useTranslation('dashboard');

  const profileHref = profileId
    ? ROUTE_PATHS.PROFILES.DETAIL.replace('$profileId', profileId)
    : ROUTE_PATHS.PROFILES.LIST;

  return (
    <Card className="border-amber-200/60 bg-amber-50/40 dark:border-amber-900/40 dark:bg-amber-950/20">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <div className="flex size-8 items-center justify-center rounded-md bg-amber-100 dark:bg-amber-900/40">
            <Lightbulb className="size-4 text-amber-600 dark:text-amber-400" />
          </div>
          {t('missingSkills.improve.title')}
        </CardTitle>
        <CardDescription>{t('missingSkills.improve.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button variant="outline" size="sm" asChild={true}>
          <Link to={profileHref} className="gap-1">
            {t('missingSkills.improve.cta')}
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function ComingSoonCard(): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <div className="flex size-8 items-center justify-center rounded-md bg-muted">
            <BookOpen className="size-4 text-muted-foreground" />
          </div>
          {t('missingSkills.comingSoon.title')}
        </CardTitle>
        <CardDescription>{t('missingSkills.comingSoon.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <Button variant="ghost" size="sm" asChild={true}>
          <Link to={ROUTE_PATHS.JOBS.LIST} className="gap-1">
            {t('missingSkills.comingSoon.cta')}
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

export { CommonMissingSkillsWidget };
