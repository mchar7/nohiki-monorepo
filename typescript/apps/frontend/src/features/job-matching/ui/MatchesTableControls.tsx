import type { useReactTable } from '@tanstack/react-table';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Columns3 } from 'lucide-react';
import { type JSX, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui/button.tsx';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/shared/ui/dropdown-menu.tsx';
import { Label } from '@/shared/ui/label.tsx';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/ui/select.tsx';

const PAGE_SIZE_SMALL: number = 10;
const PAGE_SIZE_MEDIUM: number = 20;
const PAGE_SIZE_LARGE: number = 30;
const PAGE_SIZE_XLARGE: number = 50;
const PAGE_SIZE_OPTIONS: readonly number[] = [
  PAGE_SIZE_SMALL,
  PAGE_SIZE_MEDIUM,
  PAGE_SIZE_LARGE,
  PAGE_SIZE_XLARGE,
];

function ColumnVisibilityItem<TData>({
  column,
}: {
  readonly column: ReturnType<ReturnType<typeof useReactTable<TData>>['getAllColumns']>[number];
}): JSX.Element {
  const handleCheckedChange = (value: boolean): void => {
    column.toggleVisibility(value);
  };

  return (
    <DropdownMenuCheckboxItem
      className="capitalize"
      checked={column.getIsVisible()}
      onCheckedChange={handleCheckedChange}
    >
      {column.id.replaceAll('_', ' ')}
    </DropdownMenuCheckboxItem>
  );
}

function TableToolbar<TData>({
  table,
}: {
  readonly table: ReturnType<typeof useReactTable<TData>>;
}): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  return (
    <div className="flex items-center justify-between">
      <div className="text-muted-foreground text-sm">
        {table.getFilteredSelectedRowModel().rows.length > 0 ? (
          <span>
            {`${table.getFilteredSelectedRowModel().rows.length} / ${table.getFilteredRowModel().rows.length}`}{' '}
            {t('common:labels.selected')}
          </span>
        ) : null}
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger asChild={true}>
          <Button variant="outline" size="sm">
            <Columns3 className="mr-2 size-4" />
            {t('common:columns')}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          {table
            .getAllColumns()
            .filter((column) => column.getCanHide())
            .map((column) => (
              <ColumnVisibilityItem key={column.id} column={column} />
            ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function TablePagination<TData>({
  table,
}: {
  readonly table: ReturnType<typeof useReactTable<TData>>;
}): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  const handlePageSizeChange = (value: string): void => {
    table.setPageSize(Number(value));
  };

  return (
    <div className="flex items-center justify-between">
      <PageSizeSelector table={table} onPageSizeChange={handlePageSizeChange} />
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        {t('common:pagination.pageOf', {
          current: table.getState().pagination.pageIndex + 1,
          total: table.getPageCount() || 1,
        })}
      </div>
      <PageNavButtons table={table} />
    </div>
  );
}

function PageSizeSelector<TData>({
  table,
  onPageSizeChange,
}: {
  readonly table: ReturnType<typeof useReactTable<TData>>;
  readonly onPageSizeChange: (value: string) => void;
}): JSX.Element {
  const { t } = useTranslation(['common']);
  const rowsPerPageId = useId();

  return (
    <div className="hidden items-center gap-2 lg:flex">
      <Label htmlFor={rowsPerPageId} className="text-sm">
        {t('common:pagination.rowsPerPage')}
      </Label>
      <Select value={`${table.getState().pagination.pageSize}`} onValueChange={onPageSizeChange}>
        <SelectTrigger className="w-20" id={rowsPerPageId}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PAGE_SIZE_OPTIONS.map((size) => (
            <SelectItem key={size} value={`${size}`}>
              {size}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function PageNavButtons<TData>({
  table,
}: {
  readonly table: ReturnType<typeof useReactTable<TData>>;
}): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);

  const handleFirstPage = (): void => {
    table.setPageIndex(0);
  };
  const handlePreviousPage = (): void => {
    table.previousPage();
  };
  const handleNextPage = (): void => {
    table.nextPage();
  };
  const handleLastPage = (): void => {
    table.setPageIndex(table.getPageCount() - 1);
  };

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon"
        className="hidden size-8 lg:flex"
        onClick={handleFirstPage}
        disabled={!table.getCanPreviousPage()}
      >
        <ChevronsLeft className="size-4" />
        <span className="sr-only">{t('common:pagination.first')}</span>
      </Button>
      <Button
        variant="outline"
        size="icon"
        className="size-8"
        onClick={handlePreviousPage}
        disabled={!table.getCanPreviousPage()}
      >
        <ChevronLeft className="size-4" />
        <span className="sr-only">{t('jobs:pagination.previous')}</span>
      </Button>
      <Button
        variant="outline"
        size="icon"
        className="size-8"
        onClick={handleNextPage}
        disabled={!table.getCanNextPage()}
      >
        <ChevronRight className="size-4" />
        <span className="sr-only">{t('jobs:pagination.next')}</span>
      </Button>
      <Button
        variant="outline"
        size="icon"
        className="hidden size-8 lg:flex"
        onClick={handleLastPage}
        disabled={!table.getCanNextPage()}
      >
        <ChevronsRight className="size-4" />
        <span className="sr-only">{t('common:pagination.last')}</span>
      </Button>
    </div>
  );
}

export { TablePagination, TableToolbar };
