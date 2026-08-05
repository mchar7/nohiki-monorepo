import { Link } from '@tanstack/react-router';
import type { LucideIcon } from 'lucide-react';
import {
  Briefcase,
  Calendar,
  Check,
  ClipboardCopy,
  DollarSign,
  ExternalLink,
  Globe,
  Languages,
  MapPin,
} from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { JobListingResponse } from '@/shared/api';
import {
  cn,
  formatLanguage,
  formatSalaryRange,
  getSafeExternalUrl,
  useCopyToClipboard,
} from '@/shared/lib';
import { ActionBar } from '@/shared/ui/action-bar.tsx';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { CompanyLogo } from '@/shared/ui/company-logo.tsx';
import { Separator } from '@/shared/ui/separator.tsx';
import { ShareButton } from '@/shared/ui/share-button.tsx';

/** Pairs each item with a key that stays stable and unique even when labels repeat. */
function withOccurrenceKeys<T>(
  items: readonly T[],
  toLabel: (item: T) => string,
): ReadonlyArray<{ readonly item: T; readonly key: string }> {
  const occurrenceCounts = new Map<string, number>();
  return items.map((item) => {
    const label = toLabel(item);
    const occurrence = occurrenceCounts.get(label) ?? 0;
    occurrenceCounts.set(label, occurrence + 1);
    return { item, key: `${label}#${occurrence}` };
  });
}

interface JobDetailViewProps {
  readonly listing: JobListingResponse;
}

function JobDetailView({ listing }: JobDetailViewProps): JSX.Element {
  return (
    <div className="space-y-6">
      <JobHeader listing={listing} />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <JobDescription description={listing.description} />
          <JobSkills skills={listing.required_skills} />
        </div>
        <div className="space-y-6">
          <JobMetaSidebar listing={listing} />
          <JobActions description={listing.description} listingUrl={listing.listing_url} />
        </div>
      </div>
    </div>
  );
}

function JobHeader({ listing }: { readonly listing: JobListingResponse }): JSX.Element {
  const { t } = useTranslation(['jobs']);
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-2">
            <CardTitle className="text-2xl">{listing.title}</CardTitle>
            <CardDescription className="flex items-center gap-2 text-base">
              <CompanyLogo companyName={listing.company_name} size="md" />
              {listing.company_name ? (
                <Link
                  to="/jobs"
                  search={{ company: listing.company_name }}
                  className="transition-colors hover:text-primary hover:underline"
                  aria-label={t('jobs:card.filterByCompany', { company: listing.company_name })}
                >
                  {listing.company_name}
                </Link>
              ) : (
                <span>{t('jobs:detail.unknownCompany')}</span>
              )}
            </CardDescription>
          </div>
          <Badge variant="outline" className="shrink-0 capitalize">
            {listing.source}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-4 text-muted-foreground text-sm">
          {listing.location_raw ? (
            <span className="flex items-center gap-1.5">
              <MapPin className="size-4" aria-hidden="true" />
              {listing.location_raw}
            </span>
          ) : null}
          {listing.work_arrangement ? (
            <span className="flex items-center gap-1.5">
              <Briefcase className="size-4" aria-hidden="true" />
              <span className="capitalize">{listing.work_arrangement}</span>
            </span>
          ) : null}
          {listing.seniority_level ? (
            <span className="flex items-center gap-1.5">
              <Globe className="size-4" aria-hidden="true" />
              <span className="capitalize">{listing.seniority_level}</span>
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function JobDescription({ description }: { readonly description: string | null }): JSX.Element {
  const { t } = useTranslation(['jobs']);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t('jobs:detail.about')}</CardTitle>
      </CardHeader>
      <CardContent>
        {description ? (
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <p className="whitespace-pre-wrap">{description}</p>
          </div>
        ) : (
          <p className="text-muted-foreground italic">{t('jobs:card.noDescription')}</p>
        )}
      </CardContent>
    </Card>
  );
}

function JobSkills({ skills }: { readonly skills: readonly string[] }): JSX.Element {
  const { t } = useTranslation(['jobs']);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t('jobs:detail.skills')}</CardTitle>
      </CardHeader>
      <CardContent>
        {skills.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {withOccurrenceKeys(skills, (skill) => skill).map(({ item: skill, key }) => (
              <Badge key={key} variant="secondary">
                {skill}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground italic">{t('jobs:detail.noSkills')}</p>
        )}
      </CardContent>
    </Card>
  );
}

function JobMetaSidebar({ listing }: { readonly listing: JobListingResponse }): JSX.Element {
  const { t, i18n } = useTranslation(['jobs']);
  const formattedSalary = formatSalaryRange({
    min: listing.salary_min,
    max: listing.salary_max,
    currency: listing.salary_currency,
    frequency: listing.salary_frequency,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t('jobs:detail.overview')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <MetaRow icon={Globe} label={t('jobs:detail.source')} value={listing.source} />
        <Separator />
        {listing.language ? (
          <>
            <MetaRow
              icon={Languages}
              label={t('jobs:detail.language')}
              value={formatLanguage(listing.language, i18n.resolvedLanguage ?? i18n.language)}
              valueClassName="normal-case"
            />
            <Separator />
          </>
        ) : null}
        {formattedSalary ? (
          <>
            <MetaRow
              icon={DollarSign}
              label={t('jobs:detail.salary')}
              value={formattedSalary}
              valueClassName="normal-case"
            />
            <Separator />
          </>
        ) : null}
        {listing.posted_at ? (
          <MetaRow
            icon={Calendar}
            label={t('jobs:detail.postedAt')}
            value={formatDate(listing.posted_at)}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

function MetaRow({
  icon: Icon,
  label,
  value,
  valueClassName,
}: {
  readonly icon: LucideIcon;
  readonly label: string;
  readonly value: string;
  readonly valueClassName?: string;
}): JSX.Element {
  return (
    <div className="flex items-start gap-3">
      <Icon className="mt-0.5 size-4 text-muted-foreground" aria-hidden="true" />
      <div className="space-y-1">
        <p className="font-medium text-sm">{label}</p>
        <p className={cn('text-muted-foreground text-sm', valueClassName ?? 'capitalize')}>
          {value}
        </p>
      </div>
    </div>
  );
}

function JobActions({
  description,
  listingUrl,
}: {
  readonly description: string | null;
  readonly listingUrl: string;
}): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const [copy, isCopied] = useCopyToClipboard();
  const safeListingUrl = getSafeExternalUrl(listingUrl);

  const handleCopyJd = async (): Promise<void> => {
    if (description) {
      await copy(description);
    }
  };

  return (
    <Card>
      <CardContent className="pt-6">
        <ActionBar
          primaryAction={
            safeListingUrl ? (
              <Button className="w-full" asChild={true}>
                <a href={safeListingUrl} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="mr-2 size-4" aria-hidden="true" />
                  {t('actions.viewOriginal')}
                </a>
              </Button>
            ) : (
              <Button className="w-full" disabled={true}>
                <ExternalLink className="mr-2 size-4" aria-hidden="true" />
                {t('actions.viewOriginal')}
              </Button>
            )
          }
          secondaryActions={[
            safeListingUrl ? <ShareButton key="share" url={safeListingUrl} /> : null,
            <Button
              key="copy-jd"
              variant="ghost"
              size="icon"
              onClick={handleCopyJd}
              disabled={!description}
              aria-label={t('actions.copyJobDescription')}
            >
              {isCopied ? (
                <Check className="size-4" aria-hidden="true" />
              ) : (
                <ClipboardCopy className="size-4" aria-hidden="true" />
              )}
            </Button>,
          ]}
        />
      </CardContent>
    </Card>
  );
}

function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export { JobDetailView };
