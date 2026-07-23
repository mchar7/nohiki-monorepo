import { useRouter, useRouterState } from '@tanstack/react-router';
import { Loader2, RefreshCw } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { useFileUpload } from '@/features/attachments';
import { UploadDialog, useAttachments } from '@/features/attachments/index.ts';
import { useDocuments } from '@/features/document-generation/index.ts';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { cn } from '@/shared/lib';
import {
  handleNavigationPromise,
  useDocumentTitle,
  useIsMobileLayout,
  useMainScrollRef,
  usePullToRefresh,
} from '@/shared/lib/index.ts';
import { Button } from '@/shared/ui/button.tsx';
import { PageHeader } from '@/shared/ui/PageHeader.tsx';
import { PageDropZone } from '@/shared/ui/page-drop-zone.tsx';
import { PendingMutationBadge } from '@/shared/ui/pending-mutation-badge.tsx';
import { PullIndicator } from '@/shared/ui/pull-indicator.tsx';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs.tsx';
import { PageLayout } from '@/widgets/layout/index.ts';
import { AllTabContent, GeneratedTabContent, UploadedTabContent } from './DocumentTabContent.tsx';
import type { DocumentTab } from './DocumentTabContentModel.ts';
import { PAGE_SIZE } from './DocumentTabContentModel.ts';

/** Statuses indicating active document generation */
const ACTIVE_STATUSES: ReadonlySet<string> = new Set(['pending', 'processing']);

interface RouterSearchState {
  location: { search: Record<string, unknown> };
}

/** Reads the current `tab` search param from the URL. */
function selectTabSearch(state: RouterSearchState): DocumentTab {
  const { tab } = state.location.search;
  if (tab === 'uploaded' || tab === 'generated') {
    return tab;
  }
  return 'all';
}

/** Extracts `docPage` from URL search params, defaulting to 1. */
function selectDocPage(state: RouterSearchState): number {
  const p = state.location.search.docPage;
  return typeof p === 'number' ? p : 1;
}

/** Extracts `attachPage` from URL search params, defaulting to 1. */
function selectAttachPage(state: RouterSearchState): number {
  const p = state.location.search.attachPage;
  return typeof p === 'number' ? p : 1;
}

function createFileDropHandler(
  handleUpload: (file: File) => Promise<void>,
): (files: FileList) => void {
  return (files: FileList): void => {
    const [file] = files;
    if (file) {
      handleUpload(file).catch(() => undefined);
    }
  };
}

function DocumentList(): JSX.Element {
  const router = useRouter();
  const activeTab = useRouterState({ select: selectTabSearch });
  const docPageState = useRouterState({ select: selectDocPage });
  const attachPageState = useRouterState({ select: selectAttachPage });
  const documentsQuery = useDocuments(docPageState, PAGE_SIZE);
  const attachmentsQuery = useAttachments(attachPageState, PAGE_SIZE);
  const { isUploading, handleUpload } = useFileUpload(() => attachmentsQuery.refetch());
  const handleFileDrop = createFileDropHandler(handleUpload);

  const isMobile = useIsMobileLayout();
  const mainScrollRef = useMainScrollRef();

  const refetchAll = (): void => {
    documentsQuery.refetch();
    attachmentsQuery.refetch();
  };

  const { isRefreshing, pullDistance } = usePullToRefresh({
    ref: mainScrollRef,
    onRefresh: refetchAll,
    enabled: isMobile,
  });

  const isLoading = documentsQuery.isLoading || attachmentsQuery.isLoading;
  const hasActiveDocuments =
    documentsQuery.data?.items.some((item) => ACTIVE_STATUSES.has(item.status)) ?? false;

  const navigateTab = (tab: DocumentTab): void => {
    handleNavigationPromise(
      router.navigate({ to: '/documents', search: { tab, docPage: 1, attachPage: 1 } }),
    );
  };
  const setDocPage = (page: number): void => {
    handleNavigationPromise(
      router.navigate({
        to: '/documents',
        search: (prev: Record<string, unknown>) => ({ ...prev, docPage: page }),
      }),
    );
  };
  const setAttachPage = (page: number): void => {
    handleNavigationPromise(
      router.navigate({
        to: '/documents',
        search: (prev: Record<string, unknown>) => ({ ...prev, attachPage: page }),
      }),
    );
  };

  return (
    <PageDropZone onDrop={handleFileDrop} disabled={isUploading}>
      <PageLayout className="space-y-6">
        <PullIndicator pullDistance={pullDistance} isRefreshing={isRefreshing} />
        <DocumentListHeader onRefresh={refetchAll} isRefreshing={isLoading} />
        <StatusIndicators hasActiveDocuments={hasActiveDocuments} />
        <DocumentTabs
          activeTab={activeTab}
          onTabChange={navigateTab}
          documentsQuery={documentsQuery}
          attachmentsQuery={attachmentsQuery}
          isLoading={isLoading}
          docPage={docPageState}
          attachPage={attachPageState}
          onDocPageChange={setDocPage}
          onAttachPageChange={setAttachPage}
          onRetry={refetchAll}
        />
      </PageLayout>
    </PageDropZone>
  );
}

function StatusIndicators({
  hasActiveDocuments,
}: {
  readonly hasActiveDocuments: boolean;
}): JSX.Element {
  return (
    <div className="flex items-center gap-3">
      <PendingMutationBadge entityType="document" />
      <PendingMutationBadge entityType="attachment" />
      {hasActiveDocuments ? <AutoRefreshIndicator /> : null}
    </div>
  );
}

/** Subtle indicator shown when the list is auto-polling for active documents */
function AutoRefreshIndicator(): JSX.Element {
  const { t } = useTranslation(['common']);

  return (
    <span className="inline-flex items-center gap-1.5 text-muted-foreground text-xs">
      <Loader2 className="size-3 animate-spin" />
      {t('common:states.autoRefreshing')}
    </span>
  );
}

interface DocumentTabsProps {
  readonly activeTab: DocumentTab;
  readonly onTabChange: (tab: DocumentTab) => void;
  readonly documentsQuery: AllTabContentProps['documentsQuery'];
  readonly attachmentsQuery: AllTabContentProps['attachmentsQuery'];
  readonly isLoading: boolean;
  readonly docPage: number;
  readonly attachPage: number;
  readonly onDocPageChange: (page: number) => void;
  readonly onAttachPageChange: (page: number) => void;
  readonly onRetry: () => void;
}

// Re-import the prop type for documentsQuery/attachmentsQuery
type AllTabContentProps = Parameters<typeof AllTabContent>[0];

function DocumentTabs({
  activeTab,
  onTabChange,
  documentsQuery,
  attachmentsQuery,
  isLoading,
  docPage,
  attachPage,
  onDocPageChange,
  onAttachPageChange,
  onRetry,
}: DocumentTabsProps): JSX.Element {
  const { t } = useTranslation(['documents']);

  return (
    <Tabs value={activeTab} onValueChange={(v: string) => onTabChange(v as DocumentTab)}>
      <TabsList>
        <TabsTrigger value="all">{t('documents:tabs.all')}</TabsTrigger>
        <TabsTrigger value="uploaded">{t('documents:tabs.uploaded')}</TabsTrigger>
        <TabsTrigger value="generated">{t('documents:tabs.generated')}</TabsTrigger>
      </TabsList>

      <TabsContent value="all" className="mt-4">
        <AllTabContent
          documentsQuery={documentsQuery}
          attachmentsQuery={attachmentsQuery}
          isLoading={isLoading}
          docPage={docPage}
          attachPage={attachPage}
          onDocPageChange={onDocPageChange}
          onAttachPageChange={onAttachPageChange}
          onRetry={onRetry}
        />
      </TabsContent>

      <TabsContent value="uploaded" className="mt-4">
        <UploadedTabContent
          query={attachmentsQuery}
          page={attachPage}
          onPageChange={onAttachPageChange}
        />
      </TabsContent>

      <TabsContent value="generated" className="mt-4">
        <GeneratedTabContent query={documentsQuery} page={docPage} onPageChange={onDocPageChange} />
      </TabsContent>
    </Tabs>
  );
}

interface PageHeaderProps {
  readonly onRefresh: () => void;
  readonly isRefreshing: boolean;
}

function DocumentListHeader({ onRefresh, isRefreshing }: PageHeaderProps): JSX.Element {
  const { t } = useTranslation(['documents', 'common']);

  useDocumentTitle(t('pages.list.title'));

  const refreshAction = (
    <div className="flex items-center gap-2">
      <UploadDialog />
      <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
        <RefreshCw className={cn('mr-2 size-4', isRefreshing && 'animate-spin')} />
        {t('common:actions.refresh')}
      </Button>
    </div>
  );

  return (
    <PageHeader
      title={t('documents:pages.list.title')}
      description={t('documents:pages.list.description')}
      backTo={ROUTE_PATHS.HOME}
      preferHistory={true}
      actions={refreshAction}
    />
  );
}

export { DocumentList };
