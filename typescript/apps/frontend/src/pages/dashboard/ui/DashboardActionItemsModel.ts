import type { LucideIcon } from 'lucide-react';
import { Download, Plus, Star, UserCircle } from 'lucide-react';
import { ROUTE_PATHS } from '@/shared/config';
import { getSafeGeneratedDocumentUrl } from '@/shared/lib';

/** Minimum fit_score (0-100 integer scale) to qualify as a high-quality match */
const HIGH_QUALITY_SCORE_THRESHOLD: number = 70;

/** Maximum number of action items displayed at once */
const MAX_ACTION_ITEMS: number = 4;

/** Number of profiles below which "create another" is suggested */
const PROFILE_SUGGESTION_THRESHOLD: number = 3;

interface DashboardActionItemsProps {
  readonly profiles: readonly {
    id: string;
    pref_name?: string;
    user_skills?: readonly unknown[];
  }[];
  readonly correlations: readonly {
    id: string;
    fit_score: number;
    status: string;
  }[];
  readonly documents: readonly {
    request_id: string;
    status: string;
    download_url?: string | null;
  }[];
}

interface ActionItem {
  id: string;
  icon: LucideIcon;
  title: string;
  description: string;
  href: string;
  priority: number;
}

type TranslationFn = (key: string, options?: Record<string, unknown>) => string;

/** Suggests completing skills for the first profile missing them. */
function buildSkillsAction(
  profiles: DashboardActionItemsProps['profiles'],
  t: TranslationFn,
): ActionItem | null {
  const target = profiles.find((p) => !p.user_skills || p.user_skills.length === 0);
  if (!target) {
    return null;
  }
  return {
    id: 'complete-skills',
    icon: UserCircle,
    title: t('actionItems.completeSkills.title'),
    description: t('actionItems.completeSkills.description'),
    href: ROUTE_PATHS.PROFILES.DETAIL.replace('$profileId', target.id),
    priority: 1,
  };
}

/** Suggests reviewing high-quality evaluated matches. */
function buildMatchesAction(
  correlations: DashboardActionItemsProps['correlations'],
  t: TranslationFn,
): ActionItem | null {
  const count = correlations.filter(
    (c) => c.status === 'EVALUATED' && c.fit_score >= HIGH_QUALITY_SCORE_THRESHOLD,
  ).length;
  if (count === 0) {
    return null;
  }
  return {
    id: 'review-matches',
    icon: Star,
    title: t('actionItems.reviewMatches.title', { count }),
    description: t('actionItems.reviewMatches.description'),
    href: ROUTE_PATHS.JOBS.MATCHES,
    priority: 2,
  };
}

/** Suggests downloading a completed document. */
function buildDownloadAction(
  documents: DashboardActionItemsProps['documents'],
  t: TranslationFn,
): ActionItem | null {
  const doc = documents.find((d) => d.status === 'COMPLETED' && d.download_url);
  const downloadUrl = getSafeGeneratedDocumentUrl(doc?.download_url, window.location.origin);
  if (!downloadUrl) {
    return null;
  }
  return {
    id: 'download-resume',
    icon: Download,
    title: t('actionItems.downloadResume.title'),
    description: t('actionItems.downloadResume.description'),
    href: downloadUrl,
    priority: 3,
  };
}

/** Suggests creating another profile when below the threshold. */
function buildProfileAction(
  profiles: DashboardActionItemsProps['profiles'],
  t: TranslationFn,
): ActionItem | null {
  if (profiles.length >= PROFILE_SUGGESTION_THRESHOLD) {
    return null;
  }
  return {
    id: 'create-profile',
    icon: Plus,
    title: t('actionItems.createProfile.title'),
    description: t('actionItems.createProfile.description'),
    href: ROUTE_PATHS.PROFILES.NEW,
    priority: 4,
  };
}

/**
 * Computes a prioritized list of contextual action items based on user state.
 *
 * Runtime: O(P + C + D + A log A), where P/C/D are input lengths and A is the
 * bounded candidate count (currently 4), so the sort is effectively O(1).
 */
function computeActionItems(
  profiles: DashboardActionItemsProps['profiles'],
  correlations: DashboardActionItemsProps['correlations'],
  documents: DashboardActionItemsProps['documents'],
  t: TranslationFn,
): ActionItem[] {
  const candidates = [
    buildSkillsAction(profiles, t),
    buildMatchesAction(correlations, t),
    buildDownloadAction(documents, t),
    buildProfileAction(profiles, t),
  ];
  return candidates
    .filter((item): item is ActionItem => item !== null)
    .sort((a, b) => a.priority - b.priority)
    .slice(0, MAX_ACTION_ITEMS);
}

export type { ActionItem, DashboardActionItemsProps };
export { computeActionItems };
