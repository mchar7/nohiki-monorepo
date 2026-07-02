import type { Column, ColumnDef, HeaderContext, Row } from '@tanstack/react-table';
import type { TFunction } from 'i18next';
import type { JSX } from 'react';
import type { FeedbackType, JobCorrelationResponse } from '@/shared/api';
import {
  ActionsCell,
  CreatedAtCell,
  LocationCell,
  RowSelectCell,
  ScoreCell,
  SelectHeaderCell,
  SortableColumnHeader,
  StatusCell,
  TitleCell,
} from './matchesTableCells.tsx';

function createColumns(
  t: TFunction<['jobs', 'common']>,
  onFeedback: ((correlationId: string, type: 'like' | 'dislike') => Promise<void>) | undefined,
  onStatusAction: (correlationId: string, feedbackType: FeedbackType) => void,
  isStatusActionPending: boolean,
): ColumnDef<JobCorrelationResponse>[] {
  return [
    {
      id: 'select',
      header: (context: HeaderContext<JobCorrelationResponse, unknown>): JSX.Element => (
        <SelectHeaderCell {...context} t={t} />
      ),
      cell: ({ row }: { row: Row<JobCorrelationResponse> }): JSX.Element => (
        <RowSelectCell row={row} t={t} />
      ),
      enableSorting: false,
      enableHiding: false,
    },
    {
      accessorKey: 'fit_score',
      header: ({ column }: { column: Column<JobCorrelationResponse> }): JSX.Element => (
        <SortableColumnHeader column={column} label={t('jobs:match.score')} />
      ),
      cell: ({ row }: { row: Row<JobCorrelationResponse> }): JSX.Element => <ScoreCell row={row} />,
    },
    {
      accessorKey: 'listing_title',
      header: t('jobs:card.company'),
      cell: ({ row }: { row: Row<JobCorrelationResponse> }): JSX.Element => <TitleCell row={row} />,
      enableHiding: false,
    },
    {
      accessorKey: 'listing_location',
      header: t('jobs:card.location'),
      cell: ({ row }: { row: Row<JobCorrelationResponse> }): JSX.Element => (
        <LocationCell row={row} />
      ),
    },
    {
      accessorKey: 'status',
      header: t('jobs:match.status'),
      cell: ({ row }: { row: Row<JobCorrelationResponse> }): JSX.Element => (
        <StatusCell row={row} t={t} />
      ),
    },
    {
      accessorKey: 'created_at',
      header: ({ column }: { column: Column<JobCorrelationResponse> }): JSX.Element => (
        <SortableColumnHeader column={column} label={t('jobs:match.matchedAt')} />
      ),
      cell: ({ row }: { row: Row<JobCorrelationResponse> }): JSX.Element => (
        <CreatedAtCell row={row} />
      ),
    },
    {
      id: 'actions',
      cell: ({ row }: { row: Row<JobCorrelationResponse> }): JSX.Element => (
        <ActionsCell
          row={row}
          onFeedback={onFeedback}
          onStatusAction={onStatusAction}
          isStatusActionPending={isStatusActionPending}
          t={t}
        />
      ),
    },
  ];
}

export { createColumns };
