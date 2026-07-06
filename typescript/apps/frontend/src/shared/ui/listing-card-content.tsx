import { Briefcase, Clock, Globe, MapPin } from 'lucide-react';
import type { JSX, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { extractBaseLanguage, formatLanguage, formatRelativeTime } from '@/shared/lib';
import { Badge } from '@/shared/ui/badge';
import { CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/shared/ui/card';
import { CompanyLogo } from '@/shared/ui/company-logo';

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

interface ListingCardContentProps {
  readonly title: ReactNode;
  readonly companyName: ReactNode;
  readonly locationRaw: string | null;
  readonly workArrangement: string | null;
  readonly requiredSkills: readonly string[];
  readonly postedAt: string | null;
  readonly language: string | null;
  readonly rightActions?: ReactNode;
  readonly metaRowExtra?: ReactNode;
  readonly children?: ReactNode;
}

function ListingCardLanguageBadge({
  language,
}: {
  readonly language: string | null;
}): JSX.Element | null {
  const { t, i18n } = useTranslation(['jobs']);

  if (!language) {
    return null;
  }

  const uiLocale = i18n.resolvedLanguage ?? i18n.language;
  const listingBase = extractBaseLanguage(language);
  const uiBase = extractBaseLanguage(uiLocale);

  if (listingBase === uiBase) {
    return null;
  }

  const displayName = formatLanguage(language, uiLocale);

  return (
    <Badge
      variant="secondary"
      className="gap-1 text-xs"
      aria-label={t('jobs:card.languageAriaLabel', { language: displayName })}
    >
      <Globe className="size-3" aria-hidden="true" />
      {displayName}
    </Badge>
  );
}

function ListingCardMetaRow({
  locationRaw,
  workArrangement,
  postedAt,
  extra,
}: {
  readonly locationRaw: string | null;
  readonly workArrangement: string | null;
  readonly postedAt: string | null;
  readonly extra?: ReactNode;
}): JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-muted-foreground text-sm">
      {locationRaw ? (
        <span className="flex items-center gap-1">
          <MapPin className="size-3.5" />
          {locationRaw}
        </span>
      ) : null}
      {workArrangement ? (
        <span className="flex items-center gap-1 capitalize">
          <Briefcase className="size-3.5" />
          {workArrangement}
        </span>
      ) : null}
      {postedAt ? (
        <span className="flex items-center gap-1">
          <Clock className="size-3.5" />
          {formatRelativeTime(postedAt)}
        </span>
      ) : null}
      {extra}
    </div>
  );
}

function ListingCardSkillsList({
  skills,
}: {
  readonly skills: readonly string[];
}): JSX.Element | null {
  const { t } = useTranslation(['jobs']);
  const MAX_VISIBLE = 5;

  if (skills.length === 0) {
    return null;
  }

  const visible = skills.slice(0, MAX_VISIBLE);
  const remaining = skills.length - MAX_VISIBLE;

  return (
    <div className="flex flex-wrap gap-1.5">
      {withOccurrenceKeys(visible, (skill) => skill).map(({ item: skill, key }) => (
        <Badge key={key} variant="secondary" className="text-xs">
          {skill}
        </Badge>
      ))}
      {remaining > 0 && (
        <Badge variant="secondary" className="text-xs">
          {t('card.moreSkills', { count: remaining })}
        </Badge>
      )}
    </div>
  );
}

export function ListingCardContent({
  title,
  companyName,
  locationRaw,
  workArrangement,
  requiredSkills,
  postedAt,
  language,
  rightActions,
  metaRowExtra,
  children,
}: ListingCardContentProps): JSX.Element {
  const { t } = useTranslation(['jobs']);

  return (
    <>
      <CardHeader className="px-4 pt-4 pb-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <CardTitle className="text-base">{title}</CardTitle>
            <CardDescription className="mt-1 flex items-center gap-1.5">
              <CompanyLogo
                companyName={typeof companyName === 'string' ? companyName : null}
                size="sm"
              />
              {companyName ? (
                <span className="truncate">{companyName}</span>
              ) : (
                <span className="truncate text-muted-foreground">{t('card.company')}</span>
              )}
            </CardDescription>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {rightActions}
            <ListingCardLanguageBadge language={language} />
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-4 pt-0 pb-3">
        <ListingCardMetaRow
          locationRaw={locationRaw}
          workArrangement={workArrangement}
          postedAt={postedAt}
          extra={metaRowExtra}
        />
      </CardContent>

      {children}

      {requiredSkills.length > 0 && (
        <CardFooter className="px-4 pt-0 pb-4">
          <ListingCardSkillsList skills={requiredSkills} />
        </CardFooter>
      )}
    </>
  );
}
