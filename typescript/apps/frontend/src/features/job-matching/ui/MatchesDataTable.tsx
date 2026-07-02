import { Link } from '@tanstack/react-router';
import {
  type ColumnDef,
  type ColumnFiltersState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  type RowSelectionState,
  type SortingState,
  useReactTable,
  type VisibilityState,
} from '@tanstack/react-table';
import type { TFunction } from 'i18next';
import { Briefcase, Filter, RefreshCw, Target } from 'lucide-react';
import type { JSX } from 'react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { FeedbackType, JobCorrelationResponse } from '@/shared/api';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/shared/ui/empty.tsx';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/ui/table.tsx';
import { useBulkActions } from '../lib/useBulkActions.ts';
import { BulkActionBar } from './BulkActionBar.tsx';
import { TablePagination, TableToolbar } from './MatchesTableControls.tsx';
import { createColumns } from './matchesTableColumns.tsx';

interface MatchesDataTableProps {
  readonly data: readonly JobCorrelationResponse[];
  readonly onFeedback?: (correlationId: string, type: 'like' | 'dislike') => Promise<void>;
  readonly onStatusAction: (correlationId: string, feedbackType: FeedbackType) => void;
  readonly isStatusActionPending: boolean;
  readonly hasProfiles: boolean;
  readonly hasActiveFilters: boolean;
  readonly onRefetch: () => void;
  readonly onClearFilters: () => void;
}

function EmptyNoProfiles({ t }: { readonly t: TFunction<['jobs', 'common']> }): JSX.Element {
  return (
    <Empty role="status" aria-live="polite">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Target className="size-6" />
        </EmptyMedia>
        <EmptyTitle>{t('jobs:empty.noMatchesNoProfile')}</EmptyTitle>
        <EmptyDescription>{t('jobs:empty.noMatchesNoProfileDescription')}</EmptyDescription>
      </EmptyHeader>
      <Link
        to="/profiles/new"
        className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 font-medium text-primary-foreground text-sm shadow hover:bg-primary/90"
      >
        {t('jobs:empty.createProfile')}
      </Link>
    </Empty>
  );
}

function EmptyPending({
  t,
  onRefetch,
}: {
  readonly t: TFunction<['jobs', 'common']>;
  readonly onRefetch: () => void;
}): JSX.Element {
  return (
    <Empty role="status" aria-live="polite">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Briefcase className="size-6" />
        </EmptyMedia>
        <EmptyTitle>{t('jobs:empty.noMatchesPending')}</EmptyTitle>
        <EmptyDescription>{t('jobs:empty.noMatchesPendingDescription')}</EmptyDescription>
      </EmptyHeader>
      <button
        type="button"
        onClick={onRefetch}
        className="inline-flex h-9 items-center justify-center gap-2 rounded-md border bg-background px-4 font-medium text-sm shadow-sm hover:bg-accent hover:text-accent-foreground"
      >
        <RefreshCw className="size-4" />
        {t('jobs:empty.refresh')}
      </button>
    </Empty>
  );
}

function EmptyFiltered({
  t,
  onClearFilters,
}: {
  readonly t: TFunction<['jobs', 'common']>;
  readonly onClearFilters: () => void;
}): JSX.Element {
  return (
    <Empty role="status" aria-live="polite">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Filter className="size-6" />
        </EmptyMedia>
        <EmptyTitle>{t('jobs:empty.noMatchesFiltered')}</EmptyTitle>
        <EmptyDescription>{t('jobs:empty.noMatchesFilteredDescription')}</EmptyDescription>
      </EmptyHeader>
      <button
        type="button"
        onClick={onClearFilters}
        className="inline-flex h-9 items-center justify-center gap-2 rounded-md border bg-background px-4 font-medium text-sm shadow-sm hover:bg-accent hover:text-accent-foreground"
      >
        <Filter className="size-4" />
        {t('jobs:empty.clearFilters')}
      </button>
    </Empty>
  );
}

/** Picks the contextual empty state component based on profile and filter state. */
function resolveEmptyState({
  t,
  hasProfiles,
  hasActiveFilters,
  onRefetch,
  onClearFilters,
}: {
  readonly t: TFunction<['jobs', 'common']>;
  readonly hasProfiles: boolean;
  readonly hasActiveFilters: boolean;
  readonly onRefetch: () => void;
  readonly onClearFilters: () => void;
}): JSX.Element {
  if (!hasProfiles) {
    return <EmptyNoProfiles t={t} />;
  }
  if (hasActiveFilters) {
    return <EmptyFiltered t={t} onClearFilters={onClearFilters} />;
  }
  return <EmptyPending t={t} onRefetch={onRefetch} />;
}

function TableBodyContent({
  table,
  columns,
  t,
  hasProfiles,
  hasActiveFilters,
  onRefetch,
  onClearFilters,
}: {
  readonly table: ReturnType<typeof useReactTable<JobCorrelationResponse>>;
  readonly columns: ColumnDef<JobCorrelationResponse>[];
  readonly t: TFunction<['jobs', 'common']>;
  readonly hasProfiles: boolean;
  readonly hasActiveFilters: boolean;
  readonly onRefetch: () => void;
  readonly onClearFilters: () => void;
}): JSX.Element {
  if (table.getRowModel().rows.length > 0) {
    return (
      <>
        {table.getRowModel().rows.map((row) => (
          <TableRow key={row.id} data-state={row.getIsSelected() && 'selected'}>
            {row.getVisibleCells().map((cell) => (
              <TableCell key={cell.id}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </>
    );
  }
  return (
    <TableRow>
      <TableCell colSpan={columns.length} className="py-8">
        {resolveEmptyState({ t, hasProfiles, hasActiveFilters, onRefetch, onClearFilters })}
      </TableCell>
    </TableRow>
  );
}

function MatchesDataTable({
  data,
  onFeedback,
  onStatusAction,
  isStatusActionPending,
  hasProfiles,
  hasActiveFilters,
  onRefetch,
  onClearFilters,
}: MatchesDataTableProps): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);
  const [sorting, setSorting] = useState<SortingState>([{ id: 'fit_score', desc: true }]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const columns = createColumns(t, onFeedback, onStatusAction, isStatusActionPending);

  const table = useReactTable({
    data: data as JobCorrelationResponse[],
    columns,
    state: { sorting, columnFilters, columnVisibility, rowSelection },
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const selectedRows = table.getFilteredSelectedRowModel().rows;
  const clearSelection = (): void => setRowSelection({});
  const { isBulkProcessing, handleBulkSave, handleBulkDismiss } = useBulkActions(
    selectedRows,
    clearSelection,
    t,
  );
  return (
    <div className="space-y-4">
      <TableToolbar table={table} />
      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader className="bg-muted/50">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            <TableBodyContent
              table={table}
              columns={columns}
              t={t}
              hasProfiles={hasProfiles}
              hasActiveFilters={hasActiveFilters}
              onRefetch={onRefetch}
              onClearFilters={onClearFilters}
            />
          </TableBody>
        </Table>
      </div>
      <TablePagination table={table} />
      <BulkActionBar
        selectedCount={selectedRows.length}
        onBulkSave={handleBulkSave}
        onBulkDismiss={handleBulkDismiss}
        isProcessing={isBulkProcessing}
      />
    </div>
  );
}

export { MatchesDataTable };
