import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import type { DashboardHighlightsProps } from './Dashboard.types.ts';
import { LatestDocumentCard } from './LatestDocumentCard.tsx';
import { TopMatchCard } from './TopMatchCard.tsx';

function DashboardHighlights({ topMatch, latestDocument }: DashboardHighlightsProps): JSX.Element {
  const { t } = useTranslation('dashboard');

  return (
    <section aria-label={t('highlights.ariaLabel')}>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <TopMatchCard correlation={topMatch} />
        <LatestDocumentCard document={latestDocument} />
      </div>
    </section>
  );
}

export { DashboardHighlights };
