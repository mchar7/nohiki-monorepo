import type { Row } from '@tanstack/react-table';
import type { TFunction } from 'i18next';
import { useState } from 'react';
import { toast } from 'sonner';
import type { FeedbackType, JobCorrelationResponse } from '@/shared/api';
import { useRecordFeedback } from '../api/index.ts';

interface UseBulkActionsResult {
  isBulkProcessing: boolean;
  handleBulkSave: () => void;
  handleBulkDismiss: () => void;
}

/** Encapsulates bulk save/dismiss logic for selected correlation rows. */
function useBulkActions(
  selectedRows: Row<JobCorrelationResponse>[],
  clearSelection: () => void,
  t: TFunction<['jobs', 'common']>,
): UseBulkActionsResult {
  const [isBulkProcessing, setIsBulkProcessing] = useState(false);
  const { mutateAsync: recordFeedback } = useRecordFeedback();

  const executeBulkAction = async (feedbackType: FeedbackType): Promise<void> => {
    setIsBulkProcessing(true);
    const total = selectedRows.length;
    const results = await Promise.allSettled(
      selectedRows.map((row) =>
        recordFeedback({
          params: { path: { correlation_id: row.original.id } },
          body: { feedback_type: feedbackType },
        }),
      ),
    );

    const failedCount = results.filter((r) => r.status === 'rejected').length;
    const succeededCount = total - failedCount;

    if (failedCount > 0) {
      toast.error(t('jobs:match.bulk.partialError', { failed: failedCount, total }));
    }
    if (succeededCount > 0) {
      const key =
        feedbackType === 'SAVED' ? 'jobs:match.bulk.saveSuccess' : 'jobs:match.bulk.dismissSuccess';
      toast.success(t(key, { count: succeededCount }));
    }

    clearSelection();
    setIsBulkProcessing(false);
  };

  const handleBulkSave = (): void => {
    executeBulkAction('SAVED').catch(() => undefined);
  };

  const handleBulkDismiss = (): void => {
    executeBulkAction('DISMISSED').catch(() => undefined);
  };

  return { isBulkProcessing, handleBulkSave, handleBulkDismiss };
}

export { useBulkActions };
