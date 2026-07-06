import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '@/shared/lib';
import { Button } from './button.tsx';

interface ListPaginationProps {
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
  readonly onPageChange: (page: number) => void;
}

/**
 * Reusable pagination controls for client-side paginated lists.
 * Shows "Showing X-Y of Z" with Previous/Next buttons.
 */
function ListPagination({
  page,
  pageSize,
  total,
  onPageChange,
}: ListPaginationProps): JSX.Element | null {
  const { t } = useTranslation('common');

  const totalPages = Math.ceil(total / pageSize);
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  if (total <= pageSize) {
    return null;
  }

  return (
    <div className="flex items-center justify-between border-t pt-4">
      <p className="text-muted-foreground text-sm">
        {t('pagination.showing', {
          start: formatNumber(start),
          end: formatNumber(end),
          total: formatNumber(total),
        })}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label={t('pagination.goToPrevious')}
        >
          <ChevronLeft className="mr-1 size-4" aria-hidden="true" />
          {t('pagination.previous')}
        </Button>
        <span className="px-2 text-muted-foreground text-sm">
          {t('pagination.pageOf', { current: page, total: totalPages })}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          aria-label={t('pagination.goToNext')}
        >
          {t('pagination.next')}
          <ChevronRight className="ml-1 size-4" aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}

export { ListPagination };
