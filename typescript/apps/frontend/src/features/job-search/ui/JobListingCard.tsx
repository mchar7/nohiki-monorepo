import { Link } from '@tanstack/react-router';
import { Bookmark, BookmarkCheck, Check, ClipboardCopy, DollarSign, X } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { JobListingResponse } from '@/shared/api';
import { formatSalaryRange, parseMatchExplanation, useCopyToClipboard } from '@/shared/lib';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent } from '@/shared/ui/card';
import { Highlight } from '@/shared/ui/highlight';
import { ListingCardContent } from '@/shared/ui/listing-card-content';
import { ScoreBadge } from '@/shared/ui/score-badge';
import { SeniorityBadge } from '@/shared/ui/seniority-badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/ui/tooltip';

interface JobListingCardProps {
  readonly listing: JobListingResponse;
  readonly searchQuery?: string | null;
  readonly matchScore?: number;
  readonly correlationId?: string;
  readonly correlationStatus?: string;
  readonly matchExplanation?: string | null;
  readonly onSave?: (correlationId: string) => void;
  readonly onDismiss?: (correlationId: string) => void;
}

const MAX_STRENGTHS = 2;
const MAX_CONCERNS = 1;

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

/** Strip HTML tags so raw API descriptions render as plain text. */
function stripHtmlTags(html: string): string {
  return html.replace(/<[^>]*>/gu, '');
}

function CopyDescriptionButton({ description }: { readonly description: string }): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const [copy, isCopied] = useCopyToClipboard();

  const handleClick = async (): Promise<void> => {
    await copy(description);
    toast.success(t('jobs:card.copiedToClipboard'));
  };

  return (
    <button
      type="button"
      aria-label={t('jobs:card.copyDescription')}
      onClick={handleClick}
      className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
    >
      {isCopied ? (
        <Check className="size-3.5" aria-hidden="true" />
      ) : (
        <ClipboardCopy className="size-3.5" aria-hidden="true" />
      )}
    </button>
  );
}

/** Bookmark toggle: filled when saved, outline for unsaved correlated, disabled tooltip for uncorrelated. */
function SaveButton({
  correlationId,
  correlationStatus,
  onSave,
}: {
  readonly correlationId?: string;
  readonly correlationStatus?: string;
  readonly onSave?: (correlationId: string) => void;
}): JSX.Element {
  const { t } = useTranslation(['jobs']);
  const isSaved = correlationStatus === 'SAVED';

  if (!(correlationId && onSave)) {
    return (
      <Tooltip>
        <TooltipTrigger asChild={true}>
          <span className="inline-flex size-7 items-center justify-center text-muted-foreground/50">
            <Bookmark className="size-4" aria-hidden="true" />
          </span>
        </TooltipTrigger>
        <TooltipContent>{t('jobs:card.matchToSave')}</TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      className={`size-7 ${isSaved ? 'text-primary' : 'text-muted-foreground hover:text-primary'}`}
      onClick={() => onSave(correlationId)}
      aria-label={isSaved ? t('jobs:actions.unsave') : t('jobs:actions.save')}
    >
      {isSaved ? (
        <BookmarkCheck className="size-4" aria-hidden="true" />
      ) : (
        <Bookmark className="size-4" aria-hidden="true" />
      )}
    </Button>
  );
}

function JobTitle({
  listingId,
  title,
  searchQuery,
}: {
  readonly listingId: string;
  readonly title: string;
  readonly searchQuery?: string | null;
}): JSX.Element {
  return (
    <Link
      to="/jobs/$listingId"
      params={{ listingId }}
      className="line-clamp-1 transition-colors hover:text-primary"
    >
      <Highlight text={title} query={searchQuery} />
    </Link>
  );
}

function CompanyLink({
  companyName,
  searchQuery,
}: {
  readonly companyName: string;
  readonly searchQuery?: string | null;
}): JSX.Element {
  const { t } = useTranslation(['jobs']);
  return (
    <Link
      to="/jobs"
      search={{ company: companyName }}
      className="truncate transition-colors hover:text-primary hover:underline"
      aria-label={t('card.filterByCompany', { company: companyName })}
    >
      <Highlight text={companyName} query={searchQuery} />
    </Link>
  );
}

function SalaryDisplay({ salary }: { readonly salary: string }): JSX.Element {
  return (
    <span className="flex items-center gap-1">
      <DollarSign className="size-3.5" />
      {salary}
    </span>
  );
}

function JobDescription({ description }: { readonly description: string }): JSX.Element {
  return (
    <CardContent className="px-4 pt-0 pb-3">
      <p className="line-clamp-3 text-muted-foreground text-sm">{stripHtmlTags(description)}</p>
    </CardContent>
  );
}

function CardActions({
  correlationId,
  correlationStatus,
  matchScore,
  listing,
  onSave,
  onDismiss,
}: {
  readonly correlationId?: string;
  readonly correlationStatus?: string;
  readonly matchScore?: number;
  readonly listing: JobListingResponse;
  readonly onSave?: (id: string) => void;
  readonly onDismiss?: (id: string) => void;
}): JSX.Element {
  const { t } = useTranslation(['jobs']);
  return (
    <>
      <SaveButton
        correlationId={correlationId}
        correlationStatus={correlationStatus}
        onSave={onSave}
      />
      {correlationId && onDismiss ? (
        <Button
          variant="ghost"
          size="icon"
          className="size-7 text-muted-foreground hover:text-destructive"
          onClick={() => onDismiss(correlationId)}
          aria-label={t('jobs:card.dismiss')}
        >
          <X className="size-3.5" />
        </Button>
      ) : null}
      {matchScore !== undefined && <ScoreBadge score={matchScore} />}
      <SeniorityBadge level={listing.seniority_level} />
      <Badge variant="outline" className="capitalize">
        {listing.source}
      </Badge>
      {listing.description ? <CopyDescriptionButton description={listing.description} /> : null}
    </>
  );
}

/**
 * Renders top positive/negative SHAP factors as small coloured badges.
 * Strengths appear green; concerns appear amber. Returns null when no data is available.
 */
function ShapFactorBadges({
  explanation,
}: {
  readonly explanation?: string | null;
}): JSX.Element | null {
  if (!explanation) {
    return null;
  }

  const { strengths, concerns } = parseMatchExplanation(explanation);

  if (strengths.length === 0 && concerns.length === 0) {
    return null;
  }

  const visibleStrengths = strengths.slice(0, MAX_STRENGTHS);
  const visibleConcerns = concerns.slice(0, MAX_CONCERNS);

  return (
    <CardContent className="px-4 pt-0 pb-3">
      <div className="flex flex-wrap gap-1.5">
        {withOccurrenceKeys(visibleStrengths, (factor) => factor).map(({ item: factor, key }) => (
          <Badge
            key={`strength-${key}`}
            variant="outline"
            className="border-green-500/30 bg-green-500/10 text-green-700 text-xs dark:text-green-400"
          >
            {factor}
          </Badge>
        ))}
        {withOccurrenceKeys(visibleConcerns, (factor) => factor).map(({ item: factor, key }) => (
          <Badge
            key={`concern-${key}`}
            variant="outline"
            className="border-amber-500/30 bg-amber-500/10 text-amber-700 text-xs dark:text-amber-400"
          >
            {factor}
          </Badge>
        ))}
      </div>
    </CardContent>
  );
}

function JobListingCard({
  listing,
  searchQuery,
  matchScore,
  correlationId,
  correlationStatus,
  matchExplanation,
  onSave,
  onDismiss,
}: JobListingCardProps): JSX.Element {
  const formattedSalary = formatSalaryRange({
    min: listing.salary_min,
    max: listing.salary_max,
    currency: listing.salary_currency,
    frequency: listing.salary_frequency,
    compact: true,
  });

  return (
    <Card
      role="article"
      aria-label={listing.title}
      className="group transition-all hover:border-primary/50 hover:shadow-sm"
    >
      <ListingCardContent
        title={<JobTitle listingId={listing.id} title={listing.title} searchQuery={searchQuery} />}
        companyName={
          listing.company_name ? (
            <CompanyLink companyName={listing.company_name} searchQuery={searchQuery} />
          ) : null
        }
        locationRaw={listing.location_raw}
        workArrangement={listing.work_arrangement}
        postedAt={listing.posted_at}
        requiredSkills={listing.required_skills ?? []}
        language={listing.language}
        rightActions={
          <CardActions
            correlationId={correlationId}
            correlationStatus={correlationStatus}
            matchScore={matchScore}
            listing={listing}
            onSave={onSave}
            onDismiss={onDismiss}
          />
        }
        metaRowExtra={formattedSalary ? <SalaryDisplay salary={formattedSalary} /> : null}
      >
        <ShapFactorBadges explanation={matchExplanation} />
        {listing.description ? <JobDescription description={listing.description} /> : null}
      </ListingCardContent>
    </Card>
  );
}

export { JobListingCard };
