import { SearchX } from 'lucide-react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { DOCUMENT_CATEGORIES, type DocumentCategory } from '@/features/attachments';
import type { AttachmentResponse, DocumentStatusResponse } from '@/shared/api';
import { Button } from '@/shared/ui/button.tsx';
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
import { SortSelect } from '@/shared/ui/sort-select.tsx';
import type { SortDirection } from '@/shared/ui/sort-select.types.ts';
import { EmptyState } from './DocumentEmptyState.tsx';
import type { QueryResult } from './DocumentTabContentModel.ts';
import { PAGE_SIZE } from './DocumentTabContentModel.ts';
import { DocumentTableSkeleton } from './DocumentTableSkeleton.tsx';
import { type UploadSortField, useUploadedTabDocuments } from './documentTabContentUtils.ts';
import { UnifiedDocumentCard } from './UnifiedDocumentCard.tsx';
import type { UnifiedDocument } from './UnifiedDocumentCard.types.ts';

interface AllTabContentProps {
  readonly documentsQuery: QueryResult<DocumentStatusResponse>;
  readonly attachmentsQuery: QueryResult<AttachmentResponse>;
  readonly isLoading: boolean;
  readonly docPage: number;
  readonly attachPage: number;
  readonly onDocPageChange: (page: number) => void;
  readonly onAttachPageChange: (page: number) => void;
  readonly onRetry: () => void;
}

function AllTabContent({
  documentsQuery,
  attachmentsQuery,
  isLoading,
  docPage,
  attachPage,
  onDocPageChange,
  onAttachPageChange,
  onRetry,
}: AllTabContentProps): JSX.Element {
  if (isLoading) {
    return <DocumentTableSkeleton />;
  }

  const docError = documentsQuery.error;
  const attachError = attachmentsQuery.error;
  if (docError || attachError) {
    const errorMsg = docError instanceof Error ? docError.message : String(docError ?? attachError);
    return <PanelErrorState error={errorMsg} onRetry={onRetry} />;
  }

  const uploadedItems: UnifiedDocument[] = (attachmentsQuery.data?.items ?? []).map(
    (data): UnifiedDocument => ({ type: 'uploaded', data }),
  );
  const generatedItems: UnifiedDocument[] = (documentsQuery.data?.items ?? []).map(
    (data): UnifiedDocument => ({ type: 'generated', data }),
  );
  const allItems = [...uploadedItems, ...generatedItems];

  if (allItems.length === 0) {
    return <EmptyState tab="all" />;
  }

  const totalDocs = documentsQuery.data?.total ?? 0;
  const totalAttach = attachmentsQuery.data?.total ?? 0;
  const totalCombined = totalDocs + totalAttach;

  return (
    <>
      <ResultCount total={totalCombined} />
      <div className="space-y-3">
        {allItems.map((item) => (
          <UnifiedDocumentCard key={unifiedKey(item)} document={item} />
        ))}
      </div>
      <ListPagination
        page={docPage}
        pageSize={PAGE_SIZE}
        total={totalDocs}
        onPageChange={onDocPageChange}
      />
      <ListPagination
        page={attachPage}
        pageSize={PAGE_SIZE}
        total={totalAttach}
        onPageChange={onAttachPageChange}
      />
    </>
  );
}

interface SingleTabContentProps<T> {
  readonly query: QueryResult<T>;
  readonly page: number;
  readonly onPageChange: (page: number) => void;
}

interface UploadSortState {
  sortField: UploadSortField;
  setSortField: (field: UploadSortField) => void;
  sortDirection: SortDirection;
  setSortDirection: (dir: SortDirection) => void;
  sortOptions: readonly { value: string; label: string }[];
}

function useUploadSort(): UploadSortState {
  const { t } = useTranslation(['documents']);
  const [sortField, setSortField] = useState<UploadSortField>('date');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  const sortOptions = [
    { value: 'name', label: t('documents:sort.name') },
    { value: 'date', label: t('documents:sort.date') },
  ] as const;

  return { sortField, setSortField, sortDirection, setSortDirection, sortOptions };
}

function UploadList({
  items,
  total,
  page,
  pageSize,
  onPageChange,
  hidePagination,
}: {
  readonly items: UnifiedDocument[];
  readonly total: number;
  readonly page: number;
  readonly pageSize: number;
  readonly onPageChange: (page: number) => void;
  readonly hidePagination?: boolean;
}): JSX.Element {
  return (
    <>
      <ResultCount total={total} />
      <div className="space-y-3">
        {items.map((item) => (
          <UnifiedDocumentCard key={unifiedKey(item)} document={item} />
        ))}
      </div>
      {hidePagination ? null : (
        <ListPagination page={page} pageSize={pageSize} total={total} onPageChange={onPageChange} />
      )}
    </>
  );
}

function UploadedTabContent({
  query,
  page,
  onPageChange,
}: SingleTabContentProps<AttachmentResponse>): JSX.Element {
  const [categoryFilter, setCategoryFilter] = useState<DocumentCategory | null>(null);
  const { sortField, setSortField, sortDirection, setSortDirection, sortOptions } = useUploadSort();
  const rawItems = query.data?.items ?? [];
  const { sortedItems, totalItems } = useUploadedTabDocuments({
    rawItems,
    categoryFilter,
    sortField,
    sortDirection,
  });

  if (query.isLoading) {
    return <DocumentTableSkeleton />;
  }

  if (query.error) {
    return (
      <PanelErrorState
        error={query.error instanceof Error ? query.error.message : String(query.error)}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (rawItems.length === 0) {
    return <EmptyState tab="uploaded" />;
  }

  const items: UnifiedDocument[] = sortedItems.map((data) => ({ type: 'uploaded', data }));

  return (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <CategoryFilterBar activeFilter={categoryFilter} onFilterChange={setCategoryFilter} />
        <SortSelect
          options={sortOptions}
          value={sortField}
          direction={sortDirection}
          onValueChange={(v: string) => setSortField(v as UploadSortField)}
          onDirectionChange={setSortDirection}
        />
      </div>
      {items.length === 0 && categoryFilter ? (
        <FilteredUploadsEmpty category={categoryFilter} onClear={() => setCategoryFilter(null)} />
      ) : (
        <UploadList
          items={items}
          total={totalItems}
          page={page}
          pageSize={PAGE_SIZE}
          onPageChange={onPageChange}
          hidePagination={Boolean(categoryFilter)}
        />
      )}
    </>
  );
}

function GeneratedTabContent({
  query,
  page,
  onPageChange,
}: SingleTabContentProps<DocumentStatusResponse>): JSX.Element {
  if (query.isLoading) {
    return <DocumentTableSkeleton />;
  }

  if (query.error) {
    return (
      <PanelErrorState
        error={query.error instanceof Error ? query.error.message : String(query.error)}
        onRetry={() => query.refetch()}
      />
    );
  }

  const items: UnifiedDocument[] = (query.data?.items ?? []).map(
    (data): UnifiedDocument => ({ type: 'generated', data }),
  );

  if (items.length === 0) {
    return <EmptyState tab="generated" />;
  }

  return (
    <>
      <ResultCount total={query.data?.total ?? 0} />
      <div className="space-y-3">
        {items.map((item) => (
          <UnifiedDocumentCard key={unifiedKey(item)} document={item} />
        ))}
      </div>
      <ListPagination
        page={page}
        pageSize={PAGE_SIZE}
        total={query.data?.total ?? 0}
        onPageChange={onPageChange}
      />
    </>
  );
}

interface FilteredUploadsEmptyProps {
  readonly category: DocumentCategory;
  readonly onClear: () => void;
}

function FilteredUploadsEmpty({ category, onClear }: FilteredUploadsEmptyProps): JSX.Element {
  const { t } = useTranslation(['attachments', 'common']);
  const categoryLabel = {
    resume: t('attachments:category.resume'),
    cover_letter: t('attachments:category.cover_letter'),
    portfolio: t('attachments:category.portfolio'),
    other: t('attachments:category.other'),
  } satisfies Record<DocumentCategory, string>;

  return (
    <Empty role="status" aria-live="polite" className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SearchX className="size-6" />
        </EmptyMedia>
        <EmptyTitle>{t('common:commandPalette.noResults')}</EmptyTitle>
        <EmptyDescription>
          {t('attachments:category.filterLabel')}:{' '}
          <span className="font-medium text-foreground">{categoryLabel[category]}</span>
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button onClick={onClear}>{t('attachments:category.filterAll')}</Button>
      </EmptyContent>
    </Empty>
  );
}

interface CategoryFilterBarProps {
  readonly activeFilter: DocumentCategory | null;
  readonly onFilterChange: (category: DocumentCategory | null) => void;
}

function CategoryFilterBar({ activeFilter, onFilterChange }: CategoryFilterBarProps): JSX.Element {
  const { t } = useTranslation(['attachments']);

  return (
    <fieldset
      className="mb-4 flex flex-wrap gap-2 border-0 p-0"
      aria-label={t('attachments:category.filterLabel')}
    >
      <legend className="sr-only">{t('attachments:category.filterLabel')}</legend>
      <Button
        variant={activeFilter === null ? 'default' : 'outline'}
        size="sm"
        onClick={() => onFilterChange(null)}
      >
        {t('attachments:category.filterAll')}
      </Button>
      {DOCUMENT_CATEGORIES.map((cat) => (
        <Button
          key={cat}
          variant={activeFilter === cat ? 'default' : 'outline'}
          size="sm"
          onClick={() => onFilterChange(activeFilter === cat ? null : cat)}
        >
          {t(`attachments:category.${cat}`)}
        </Button>
      ))}
    </fieldset>
  );
}

function unifiedKey(item: UnifiedDocument): string {
  return item.type === 'uploaded' ? `upload-${item.data.id}` : `gen-${item.data.request_id}`;
}

function ResultCount({ total }: { readonly total: number }): JSX.Element {
  const { t } = useTranslation(['common']);
  return (
    <p className="mb-3 text-muted-foreground text-sm">
      {t('common:counts.result', { count: total })}
    </p>
  );
}

export { AllTabContent, GeneratedTabContent, UploadedTabContent };
