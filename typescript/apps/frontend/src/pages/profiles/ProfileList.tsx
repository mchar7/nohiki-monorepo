import { Link } from '@tanstack/react-router';
import { Loader2, Plus, Users } from 'lucide-react';
import { Fragment, type JSX, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useProfileCompleteness } from '@/features/profile-management';
import {
  PENDING_ID_PREFIX,
  type ProfileResponse,
  useProfiles,
} from '@/features/profile-management/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import {
  formatRelativeTime,
  useDocumentTitle,
  useIsMobileLayout,
  useMainScrollRef,
  usePullToRefresh,
  useUrlListState,
} from '@/shared/lib/index.ts';
import { Badge } from '@/shared/ui/badge.tsx';
import { Button } from '@/shared/ui/button.tsx';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card.tsx';
import { DensityToggle } from '@/shared/ui/density-toggle.tsx';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/shared/ui/empty.tsx';
import { ListPagination } from '@/shared/ui/list-pagination.tsx';
import { PanelErrorState } from '@/shared/ui/panel-error-state.tsx';
import { PendingMutationBadge } from '@/shared/ui/pending-mutation-badge.tsx';
import { PullIndicator } from '@/shared/ui/pull-indicator.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { CardGridSkeleton } from '@/shared/ui/skeleton-layouts.tsx';
import { SortSelect } from '@/shared/ui/sort-select.tsx';
import type { SortDirection, SortOption } from '@/shared/ui/sort-select.types.ts';
import { PageLayout } from '@/widgets/layout/index.ts';

/** Maximum work arrangements to display in card preview */
const MAX_CARD_WORK_ARRANGEMENTS: number = 2;
/** Maximum keywords to show in card preview */
const MAX_CARD_KEYWORDS: number = 5;
/** Items per page for client-side pagination */
const PROFILES_PAGE_SIZE: number = 10;
/** Polling interval for CQRS eventual consistency */
const CQRS_POLL_INTERVAL_MS: number = 2000;

type ProfileSortField = 'name' | 'keywords';

/** Comparator for sorting profiles by the selected field */
function compareProfiles(
  a: ProfileResponse,
  b: ProfileResponse,
  field: ProfileSortField,
  direction: SortDirection,
): number {
  const multiplier = direction === 'asc' ? 1 : -1;
  switch (field) {
    case 'name':
      return multiplier * a.pref_name.localeCompare(b.pref_name);
    case 'keywords':
      return multiplier * (a.search_keywords.length - b.search_keywords.length);
    default:
      return 0;
  }
}

function isPendingProfile(profile: ProfileResponse): boolean {
  return profile.id.startsWith(PENDING_ID_PREFIX);
}

/** Score boundary for green/amber/red badge coloring */
const BADGE_HIGH_THRESHOLD: number = 70;
const BADGE_LOW_THRESHOLD: number = 40;

function CompletenessBadge({ profile }: Readonly<{ profile: ProfileResponse }>): JSX.Element {
  const { score } = useProfileCompleteness(profile);
  let colorClass = 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
  if (score >= BADGE_HIGH_THRESHOLD) {
    colorClass = 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400';
  } else if (score >= BADGE_LOW_THRESHOLD) {
    colorClass = 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 font-semibold text-xs tabular-nums ${colorClass}`}
    >
      {`${score.toString()}%`}
    </span>
  );
}

function ProfileCardMetadata({
  profile,
}: Readonly<{ profile: ProfileResponse }>): JSX.Element | null {
  const { t } = useTranslation('profiles');
  const timeSource = profile.updated_at ?? profile.created_at;
  const timeAgo = timeSource ? formatRelativeTime(timeSource) : null;
  const matchCount = t('card.matchCount', { count: 0 });

  if (!timeAgo) {
    return null;
  }

  return (
    <p className="text-muted-foreground text-xs">{t('card.metadata', { matchCount, timeAgo })}</p>
  );
}

interface ProfileKeywordProps {
  readonly profile: ProfileResponse;
}

function ProfileKeywords({ profile }: ProfileKeywordProps): JSX.Element {
  const { t } = useTranslation('profiles');
  if (profile.search_keywords.length === 0) {
    return <>{t('card.noKeywords')}</>;
  }
  return (
    <>
      {profile.search_keywords.slice(0, MAX_CARD_KEYWORDS).map((term, index) => (
        <Fragment key={term}>
          {index > 0 ? ', ' : null}
          <span>{term}</span>
        </Fragment>
      ))}
    </>
  );
}

function PendingProfileCard({ profile }: ProfileKeywordProps): JSX.Element {
  const { t } = useTranslation('profiles');

  return (
    <Card className="animate-pulse border-dashed opacity-70">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          {profile.pref_name}
        </CardTitle>
        <CardDescription className="text-xs">{t('card.creating')}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-muted-foreground text-sm">
          <ProfileKeywords profile={profile} />
        </p>
      </CardContent>
    </Card>
  );
}

function ProfileCard({ profile }: ProfileKeywordProps): JSX.Element {
  if (isPendingProfile(profile)) {
    return <PendingProfileCard profile={profile} />;
  }

  return (
    <Card className="transition-colors focus-within:outline-none focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 hover:border-primary/50">
      <Link to="/profiles/$profileId" params={{ profileId: profile.id }}>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>{profile.pref_name}</CardTitle>
            <CompletenessBadge profile={profile} />
          </div>
          <CardDescription className="flex flex-wrap gap-1">
            {profile.work_arrangements.slice(0, MAX_CARD_WORK_ARRANGEMENTS).map((arr) => (
              <Badge key={arr} variant="secondary" className="text-xs">
                {arr}
              </Badge>
            ))}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          <p className="line-clamp-2 text-muted-foreground text-sm">
            <ProfileKeywords profile={profile} />
          </p>
          <ProfileCardMetadata profile={profile} />
        </CardContent>
      </Link>
    </Card>
  );
}

function ProfileListSkeleton(): JSX.Element {
  return (
    <CardGridSkeleton columns="md:grid-cols-2 lg:grid-cols-3">
      {(key: string) => (
        <Card key={key}>
          <CardHeader>
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-4 w-24" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-16 w-full" />
          </CardContent>
        </Card>
      )}
    </CardGridSkeleton>
  );
}

const PROFILE_SORT_OPTIONS: readonly SortOption[] = [
  { value: 'name', label: 'Name' },
  { value: 'keywords', label: 'Keywords Count' },
];

/** Renders profile grid with sort controls, or empty/error/loading states */
function ProfileContent({
  profiles,
  totalItems,
  isLoading,
  error,
  onRetry,
  sortField,
  sortDirection,
  onSortFieldChange,
  onSortDirectionChange,
  page,
  onPageChange,
}: {
  readonly profiles: readonly ProfileResponse[];
  readonly totalItems: number;
  readonly isLoading: boolean;
  readonly error: unknown;
  readonly onRetry: () => void;
  readonly sortField: ProfileSortField;
  readonly sortDirection: SortDirection;
  readonly onSortFieldChange: (value: string) => void;
  readonly onSortDirectionChange: (dir: SortDirection) => void;
  readonly page: number;
  readonly onPageChange: (page: number) => void;
}): JSX.Element {
  const { t } = useTranslation(['navigation', 'common', 'profiles']);

  if (isLoading) {
    return <ProfileListSkeleton />;
  }

  if (error) {
    return (
      <PanelErrorState
        error={error instanceof Error ? error.message : String(error)}
        onRetry={onRetry}
      />
    );
  }

  if (profiles.length > 0) {
    return (
      <>
        <div className="flex items-center justify-between">
          <p className="text-muted-foreground text-sm">
            {t('common:counts.result', { count: totalItems })}
          </p>
          <div className="flex items-center gap-2">
            <SortSelect
              options={PROFILE_SORT_OPTIONS}
              value={sortField}
              direction={sortDirection}
              onValueChange={onSortFieldChange}
              onDirectionChange={onSortDirectionChange}
            />
            <DensityToggle />
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {profiles.map((profile) => (
            <ProfileCard key={profile.id} profile={profile} />
          ))}
        </div>
        <ListPagination
          page={page}
          pageSize={PROFILES_PAGE_SIZE}
          total={totalItems}
          onPageChange={onPageChange}
        />
      </>
    );
  }

  return (
    <Empty className="rounded-lg border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Users className="size-6" />
        </EmptyMedia>
        <EmptyTitle>{t('profiles:empty.noProfiles')}</EmptyTitle>
        <EmptyDescription>{t('profiles:empty.noProfilesDescription')}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button asChild={true}>
          <Link to={ROUTE_PATHS.PROFILES.NEW}>
            <Plus className="mr-2 size-4" />
            {t('navigation:sidebar.profiles.create')}
          </Link>
        </Button>
      </EmptyContent>
    </Empty>
  );
}

/**
 * Merges server-fetched profiles with tracked pending optimistic profiles.
 * Pending profiles are kept visible until a real profile with the same name appears
 * in the server data, indicating the CQRS projection has completed.
 */
function useMergedProfiles(serverItems: readonly ProfileResponse[]): {
  items: readonly ProfileResponse[];
  hasPending: boolean;
} {
  const pendingRef = useRef<Map<string, ProfileResponse>>(new Map());

  const realItems: ProfileResponse[] = [];
  const realNames = new Set<string>();
  for (const profile of serverItems) {
    if (isPendingProfile(profile)) {
      pendingRef.current.set(profile.id, profile);
    } else {
      realItems.push(profile);
      realNames.add(profile.pref_name);
    }
  }

  for (const [id, p] of pendingRef.current) {
    if (realNames.has(p.pref_name)) {
      pendingRef.current.delete(id);
    }
  }

  const stillPending = [...pendingRef.current.values()];
  return {
    items: [...stillPending, ...realItems],
    hasPending: stillPending.length > 0,
  };
}

export function ProfileList(): JSX.Element {
  const { t } = useTranslation(['navigation', 'common', 'profiles']);
  const [isPolling, setIsPolling] = useState(false);

  const { data, isLoading, error, refetch } = useProfiles({
    refetchInterval: isPolling ? CQRS_POLL_INTERVAL_MS : false,
  });

  const serverItems = data?.items ?? [];
  const { items: allItems, hasPending } = useMergedProfiles(serverItems);

  useEffect(() => {
    setIsPolling(hasPending);
  }, [hasPending]);

  const { page, sortField, sortDirection, setPage, setSortField, setSortDirection } =
    useUrlListState<ProfileSortField>({ route: '/profiles', defaultSort: 'name' });
  useDocumentTitle(t('navigation:sidebar.profiles.list'));

  const sortedItems = [...allItems].sort((a, b) => compareProfiles(a, b, sortField, sortDirection));
  const totalItems = sortedItems.length;
  const paginated = sortedItems.slice((page - 1) * PROFILES_PAGE_SIZE, page * PROFILES_PAGE_SIZE);

  const isMobile = useIsMobileLayout();
  const mainScrollRef = useMainScrollRef();
  const { isRefreshing, pullDistance } = usePullToRefresh({
    ref: mainScrollRef,
    onRefresh: refetch,
    enabled: isMobile,
  });

  return (
    <PageLayout className="space-y-6">
      <PullIndicator pullDistance={pullDistance} isRefreshing={isRefreshing} />
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-bold text-2xl">{t('navigation:sidebar.profiles.list')}</h1>
          <p className="text-muted-foreground">{t('profiles:pages.list.description')}</p>
        </div>
        <Button asChild={true} className="sm:shrink-0">
          <Link to={ROUTE_PATHS.PROFILES.NEW}>
            <Plus className="mr-2 size-4" />
            {t('navigation:sidebar.profiles.create')}
          </Link>
        </Button>
      </div>
      <div className="flex items-center gap-3">
        <PendingMutationBadge entityType="profile" />
      </div>
      <ProfileContent
        profiles={paginated}
        totalItems={totalItems}
        isLoading={isLoading}
        error={error}
        onRetry={refetch}
        sortField={sortField}
        sortDirection={sortDirection}
        onSortFieldChange={(v: string) => setSortField(v as ProfileSortField)}
        onSortDirectionChange={setSortDirection}
        page={page}
        onPageChange={setPage}
      />
    </PageLayout>
  );
}
