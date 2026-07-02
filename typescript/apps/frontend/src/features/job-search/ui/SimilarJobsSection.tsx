import { Link } from '@tanstack/react-router';
import { Briefcase, MapPin } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { JobListingResponse } from '@/shared/api';
import { Badge } from '@/shared/ui/badge.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { CompanyLogo } from '@/shared/ui/company-logo.tsx';

const MAX_SIMILAR_JOBS = 4;
const MIN_SKILL_OVERLAP = 2;
const MAX_VISIBLE_SKILLS = 3;

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

interface SimilarJobsSectionProps {
  readonly currentListing: JobListingResponse;
  readonly allListings: readonly JobListingResponse[];
}

interface ScoredListing {
  readonly listing: JobListingResponse;
  readonly sameCompany: boolean;
  readonly skillOverlap: number;
}

function normalizeCompanyName(companyName: string | null): string | null {
  return companyName?.toLowerCase() ?? null;
}

function buildSkillSet(skills: readonly string[]): ReadonlySet<string> {
  return new Set(skills.map((skill) => skill.toLowerCase()));
}

/** Counts shared skills between two skill arrays using a set for O(n+m) lookup. */
function countSkillOverlap(skillsA: ReadonlySet<string>, skillsB: readonly string[]): number {
  let count = 0;
  for (const skill of skillsB) {
    if (skillsA.has(skill.toLowerCase())) {
      count += 1;
    }
  }
  return count;
}

/**
 * Finds similar listings by company name match or skill overlap (≥2 shared skills).
 * Results sorted by: same company first, then by skill overlap count descending.
 */
function findSimilarListings(
  current: JobListingResponse,
  allListings: readonly JobListingResponse[],
): readonly JobListingResponse[] {
  const scored: ScoredListing[] = [];
  const currentCompany = normalizeCompanyName(current.company_name);
  const currentSkills = buildSkillSet(current.required_skills);

  for (const listing of allListings) {
    if (listing.id !== current.id) {
      const sameCompany =
        currentCompany !== null && normalizeCompanyName(listing.company_name) === currentCompany;

      const skillOverlap = countSkillOverlap(currentSkills, listing.required_skills);

      if (sameCompany || skillOverlap >= MIN_SKILL_OVERLAP) {
        scored.push({ listing, sameCompany, skillOverlap });
      }
    }
  }

  scored.sort((a, b) => {
    // Same company takes priority
    if (a.sameCompany !== b.sameCompany) {
      return a.sameCompany ? -1 : 1;
    }
    // Then by skill overlap count descending
    return b.skillOverlap - a.skillOverlap;
  });

  return scored.slice(0, MAX_SIMILAR_JOBS).map((s) => s.listing);
}

function SimilarJobsSection({
  currentListing,
  allListings,
}: SimilarJobsSectionProps): JSX.Element | null {
  const { t } = useTranslation(['jobs']);

  const similarListings = findSimilarListings(currentListing, allListings);

  if (similarListings.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t('jobs:detail.similarJobs')}</CardTitle>
        <CardDescription>{t('jobs:detail.similarJobsDescription')}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2">
          {similarListings.map((listing) => (
            <SimilarJobCard key={listing.id} listing={listing} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function SimilarJobCard({ listing }: { readonly listing: JobListingResponse }): JSX.Element {
  return (
    <Link
      to="/jobs/$listingId"
      params={{ listingId: listing.id }}
      className="group block rounded-lg border p-3 transition-colors hover:border-primary/50 hover:bg-accent/50"
    >
      <div className="space-y-1.5">
        <p className="line-clamp-1 font-medium text-sm transition-colors group-hover:text-primary">
          {listing.title}
        </p>
        <div className="flex items-center gap-1.5 text-muted-foreground text-xs">
          <CompanyLogo companyName={listing.company_name} size="sm" />
          <span className="truncate">{listing.company_name ?? ''}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground text-xs">
          {listing.location_raw ? (
            <span className="flex items-center gap-1">
              <MapPin className="size-3" aria-hidden="true" />
              <span className="truncate">{listing.location_raw}</span>
            </span>
          ) : null}
          {listing.work_arrangement ? (
            <span className="flex items-center gap-1 capitalize">
              <Briefcase className="size-3" aria-hidden="true" />
              {listing.work_arrangement}
            </span>
          ) : null}
        </div>
        {listing.required_skills.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {withOccurrenceKeys(
              listing.required_skills.slice(0, MAX_VISIBLE_SKILLS),
              (skill) => skill,
            ).map(({ item: skill, key }) => (
              <Badge key={key} variant="secondary" className="text-xs">
                {skill}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </Link>
  );
}

export { SimilarJobsSection };
