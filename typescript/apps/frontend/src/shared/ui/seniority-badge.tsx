import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from './badge.tsx';

/**
 * Maps API seniority level values to i18n keys under "jobs:card.seniority.*".
 *
 * Covers the canonical SeniorityLevel enum ("INTERN" | "ENTRY" | "MID" | "SENIOR" | "STAFF"
 * | "MANAGER" | "DIRECTOR" | "VP" | "EXECUTIVE") as well as legacy/alternate forms
 * like "MID_LEVEL" and "ENTRY_LEVEL".
 */
const LEVEL_TO_I18N_KEY: Record<string, string> = {
  INTERN: 'card.seniority.intern',
  ENTRY: 'card.seniority.entry',
  ENTRY_LEVEL: 'card.seniority.entry',
  MID: 'card.seniority.mid',
  MID_LEVEL: 'card.seniority.mid',
  SENIOR: 'card.seniority.senior',
  STAFF: 'card.seniority.staff',
  MANAGER: 'card.seniority.manager',
  DIRECTOR: 'card.seniority.director',
  VP: 'card.seniority.vp',
  EXECUTIVE: 'card.seniority.executive',
  LEAD: 'card.seniority.lead',
};

interface SeniorityBadgeProps {
  readonly level: string | null | undefined;
}

/**
 * Renders a seniority level badge (e.g. "Senior", "Mid-Level") using outline styling.
 * Returns null when the level is missing, empty, or "UNSPECIFIED".
 */
function SeniorityBadge({ level }: SeniorityBadgeProps): JSX.Element | null {
  const { t } = useTranslation(['jobs']);

  if (!level?.trim() || level === 'UNSPECIFIED') {
    return null;
  }

  const i18nKey = LEVEL_TO_I18N_KEY[level.toUpperCase()];
  if (!i18nKey) {
    return null;
  }

  return (
    <Badge variant="outline" className="text-xs">
      {t(`jobs:${i18nKey}`)}
    </Badge>
  );
}

export { SeniorityBadge };
