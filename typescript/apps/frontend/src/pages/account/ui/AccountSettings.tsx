import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { useDocumentTitle } from '@/shared/lib/index.ts';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import { PageHeader } from '@/shared/ui/index.ts';
import { PanelErrorState } from '@/shared/ui/panel-error-state.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';
import { useAccount } from '../api/index.ts';
import { DeleteAccountSection } from './DeleteAccountSection.tsx';
import { LinkedAccountsSection } from './LinkedAccountsSection.tsx';
import { ProfileSection } from './ProfileSection.tsx';
import { SecuritySection } from './SecuritySection.tsx';

function AccountSettings(): JSX.Element {
  const { data: account, isLoading, error, refetch } = useAccount();

  return (
    <PageLayout className="space-y-6">
      <AccountPageHeader />
      <AccountContent account={account} isLoading={isLoading} error={error} onRetry={refetch} />
    </PageLayout>
  );
}

function AccountPageHeader(): JSX.Element {
  const { t } = useTranslation(['account']);

  useDocumentTitle(t('pages.settings.title'));

  return (
    <PageHeader
      title={t('pages.settings.title')}
      description={t('pages.settings.description')}
      backTo={ROUTE_PATHS.HOME}
      preferHistory={true}
    />
  );
}

interface AccountContentProps {
  readonly account: ReturnType<typeof useAccount>['data'];
  readonly isLoading: boolean;
  readonly error: Error | null;
  readonly onRetry: () => void;
}

function AccountContent({
  account,
  isLoading,
  error,
  onRetry,
}: AccountContentProps): JSX.Element | null {
  if (isLoading) {
    return <AccountSkeleton />;
  }

  if (error) {
    return <PanelErrorState error={error.message} onRetry={onRetry} />;
  }

  if (!account) {
    return null;
  }

  return (
    <div className="space-y-6">
      <ProfileSection account={account} />
      <LinkedAccountsSection />
      <SecuritySection />
      <DeleteAccountSection />
    </div>
  );
}

function AccountSkeleton(): JSX.Element {
  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="space-y-4 py-6">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-64" />
          <Skeleton className="h-10 w-full" />
          <div className="grid gap-4 sm:grid-cols-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="space-y-4 py-6">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

export { AccountSettings };
