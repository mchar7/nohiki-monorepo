import { Globe } from 'lucide-react';

/** Factor for converting API 0-1 fraction to a display percentage */
const PERCENTAGE_SCALE: number = 100;

import type { JSX, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { ProfileResponse } from '@/shared/api';
import { useSkillBatch } from '@/shared/api';
import { Badge } from '@/shared/ui/badge.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { ProfileCompletenessBar } from './ProfileCompletenessBar.tsx';

interface ProfileViewCardProps {
  readonly profile: ProfileResponse;
}

function ProfileViewCard({ profile }: ProfileViewCardProps): JSX.Element {
  const { t } = useTranslation('profiles');

  const { data: skillBatchData } = useSkillBatch(profile.user_skills ?? []);
  const skillNameMap = new Map<string, string>(
    (skillBatchData?.skills ?? []).map((skill) => [skill.id, skill.display_name ?? skill.name]),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{profile.pref_name}</CardTitle>
        <CardDescription>{t('pages.detail.viewMode')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <ProfileCompletenessBar profile={profile} />
        <Section title={t('fields.searchKeywords.label')}>
          <TagList tags={profile.search_keywords} emptyText={t('fields.searchKeywords.label')} />
        </Section>

        {profile.disallowed_keywords.length > 0 && (
          <Section title={t('fields.disallowedKeywords.label')}>
            <TagList
              tags={profile.disallowed_keywords}
              variant="destructive"
              emptyText={t('fields.disallowedKeywords.label')}
            />
          </Section>
        )}

        {(profile.user_skills ?? []).length > 0 && (
          <Section title={t('fields.userSkills.label')}>
            <TagList
              tags={(profile.user_skills ?? []).map((id) => skillNameMap.get(id) ?? id)}
              emptyText={t('fields.userSkills.label')}
            />
          </Section>
        )}

        <Section title={t('fields.workArrangements.label')}>
          <TagList
            tags={profile.work_arrangements.map((arr) =>
              t(
                `fields.workArrangements.options.${arr}` as `fields.workArrangements.options.${'ON_SITE' | 'HYBRID' | 'REMOTE'}`,
              ),
            )}
            variant="outline"
            emptyText={t('fields.workArrangements.description')}
          />
        </Section>

        {profile.open_to_relocation ? (
          <div className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm">
            <Globe className="size-4 text-primary" />
            <span>{t('fields.relocation.displayLabel')}</span>
          </div>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <ThresholdDisplay
            label={t('fields.notificationThreshold.label')}
            value={profile.notification_threshold}
          />
          <ThresholdDisplay
            label={t('fields.autoTailorThreshold.label')}
            value={profile.auto_tailor_threshold}
          />
        </div>

        <ExperienceDisplay profile={profile} />
        <SalaryDisplay profile={profile} />
      </CardContent>
    </Card>
  );
}

function Section({
  title,
  children,
}: {
  readonly title: string;
  readonly children: ReactNode;
}): JSX.Element {
  return (
    <div className="space-y-2">
      <h3 className="font-medium text-muted-foreground text-sm">{title}</h3>
      {children}
    </div>
  );
}

function TagList({
  tags,
  variant = 'secondary',
  emptyText,
}: {
  readonly tags: readonly string[];
  readonly variant?: 'secondary' | 'destructive' | 'outline';
  readonly emptyText: string;
}): JSX.Element {
  if (tags.length === 0) {
    return <p className="text-muted-foreground text-sm">{emptyText}</p>;
  }
  const uniqueTags = new Set(tags);

  return (
    <div className="flex flex-wrap gap-1.5">
      {Array.from(uniqueTags, (tag) => (
        <Badge key={tag} variant={variant} className="text-xs">
          {tag}
        </Badge>
      ))}
    </div>
  );
}

function ThresholdDisplay({
  label,
  value,
}: {
  readonly label: string;
  readonly value: number | null;
}): JSX.Element {
  const displayValue = value !== null ? `${Math.round(value * PERCENTAGE_SCALE)}%` : '-';

  return (
    <div className="rounded-lg border p-4">
      <p className="text-muted-foreground text-sm">{label}</p>
      <p className="font-bold text-2xl tabular-nums">{displayValue}</p>
    </div>
  );
}

/** Cents → dollars conversion factor */
const CENTS_PER_DOLLAR: number = 100;

function formatCurrency(minorUnits: number, currency: string): string {
  const dollars = minorUnits / CENTS_PER_DOLLAR;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(dollars);
}

function ExperienceDisplay({ profile }: { readonly profile: ProfileResponse }): JSX.Element | null {
  const { t } = useTranslation('profiles');
  const experience = profile.experience_preference;
  if (!experience) {
    return null;
  }

  const years = experience.experience_years ?? 0;
  const levels = experience.seniority_levels ?? [];

  return (
    <Section title={t('fields.experience.label')}>
      <div className="space-y-3">
        <p className="text-sm">{t('fields.experience.displayYears', { count: years })}</p>
        {levels.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {levels.map((level) => (
              <Badge key={level} variant="outline" className="text-xs">
                {t(`fields.experience.seniorityOptions.${level}`)}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </Section>
  );
}

function SalaryDisplay({ profile }: { readonly profile: ProfileResponse }): JSX.Element | null {
  const { t } = useTranslation('profiles');
  const salary = profile.salary_preference;
  if (!salary) {
    return null;
  }

  const minUnits = salary.min_salary?.minor_units ?? 0;
  const targetUnits = salary.target_salary?.minor_units ?? 0;
  const currency = salary.min_salary?.currency ?? 'USD';
  const frequency = salary.preferred_frequency ?? 'ANNUALLY';

  if (minUnits === 0 && targetUnits === 0) {
    return null;
  }

  const formattedMin = formatCurrency(minUnits, currency);
  const formattedTarget = formatCurrency(targetUnits, currency);
  const frequencyLabel = t(`fields.salary.frequencyOptions.${frequency}`).toLowerCase();

  return (
    <Section title={t('fields.salary.label')}>
      <p className="font-semibold text-sm tabular-nums">
        {`${formattedMin} \u2013 ${formattedTarget} / ${frequencyLabel}`}
      </p>
    </Section>
  );
}

export { ProfileViewCard };
