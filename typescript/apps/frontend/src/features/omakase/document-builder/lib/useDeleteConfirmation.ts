import { useState } from 'react';

/**
 * Manages a two-step delete confirmation flow.
 *
 * Tracks the ID of the item pending deletion. The consumer is responsible
 * for rendering the confirmation UI and deriving display text from the
 * pending ID.
 *
 * @param onDelete - Called with the pending ID when deletion is confirmed.
 */
export function useDeleteConfirmation(onDelete: (id: string) => void): {
  readonly pendingDeleteId: string | null;
  readonly requestDelete: (id: string) => void;
  readonly confirmDelete: () => void;
  readonly cancelDelete: () => void;
} {
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const requestDelete = (id: string) => {
    setPendingDeleteId(id);
  };

  const confirmDelete = () => {
    if (pendingDeleteId) {
      onDelete(pendingDeleteId);
    }
    setPendingDeleteId(null);
  };

  const cancelDelete = () => {
    setPendingDeleteId(null);
  };

  return { pendingDeleteId, requestDelete, confirmDelete, cancelDelete } as const;
}
