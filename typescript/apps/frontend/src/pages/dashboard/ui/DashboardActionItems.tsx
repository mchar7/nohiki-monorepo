import { Link } from '@tanstack/react-router';
import { ArrowRight } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

import { ROUTE_PATHS } from '@/shared/config';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/index.ts';
import type { ActionItem, DashboardActionItemsProps } from './DashboardActionItemsModel.ts';
import { computeActionItems } from './DashboardActionItemsModel.ts';

interface ActionItemRowProps {
  readonly item: ActionItem;
}

function ActionItemRow({ item }: ActionItemRowProps): JSX.Element {
  const Icon = item.icon;
  const isExternal = item.href.startsWith('http');

  const content = (
    <>
      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
        <Icon className="size-4 text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-sm">{item.title}</p>
        <p className="text-muted-foreground text-xs">{item.description}</p>
      </div>
      <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
    </>
  );

  const rowClassName =
    'flex items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-accent/50';

  if (isExternal) {
    return (
      <a href={item.href} target="_blank" rel="noopener noreferrer" className={rowClassName}>
        {content}
      </a>
    );
  }

  return (
    <Link to={item.href} className={rowClassName}>
      {content}
    </Link>
  );
}

export function DashboardActionItems({
  profiles,
  correlations,
  documents,
}: DashboardActionItemsProps): JSX.Element {
  const { t } = useTranslation('dashboard');
  const items = computeActionItems(profiles, correlations, documents, t);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('actionItems.title')}</CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-6 text-center">
            <p className="font-medium text-muted-foreground">{t('actionItems.empty.title')}</p>
            <Link to={ROUTE_PATHS.JOBS.LIST} className="mt-2 text-primary text-sm hover:underline">
              {t('actionItems.browseJobs')}
            </Link>
          </div>
        ) : (
          <ul className="space-y-2">
            {items.map((item) => (
              <li key={item.id}>
                <ActionItemRow item={item} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
