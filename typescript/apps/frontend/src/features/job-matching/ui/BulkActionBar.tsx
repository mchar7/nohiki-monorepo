import { Bookmark, Loader2, X } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/shared/ui/button.tsx';

interface BulkActionBarProps {
  readonly selectedCount: number;
  readonly onBulkSave: () => void;
  readonly onBulkDismiss: () => void;
  readonly isProcessing: boolean;
}

/** Sticky bar rendered when table rows are selected, offering bulk save/dismiss actions. */
function BulkActionBar({
  selectedCount,
  onBulkSave,
  onBulkDismiss,
  isProcessing,
}: BulkActionBarProps): JSX.Element | null {
  const { t } = useTranslation(['jobs']);

  if (selectedCount === 0) {
    return null;
  }

  return (
    <div className="fade-in slide-in-from-bottom-2 sticky bottom-4 z-20 flex animate-in items-center justify-between gap-4 rounded-lg border bg-background/95 px-4 py-3 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <span className="font-medium text-sm">
        {t('jobs:match.bulk.selected', { count: selectedCount })}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onBulkSave} disabled={isProcessing}>
          {isProcessing ? <Loader2 className="animate-spin" /> : <Bookmark />}
          {t('jobs:match.bulk.saveAll', { count: selectedCount })}
        </Button>
        <Button variant="destructive" size="sm" onClick={onBulkDismiss} disabled={isProcessing}>
          {isProcessing ? <Loader2 className="animate-spin" /> : <X />}
          {t('jobs:match.bulk.dismissAll', { count: selectedCount })}
        </Button>
      </div>
    </div>
  );
}

export { BulkActionBar };
