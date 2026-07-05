import { type DocumentCategory, loadCategory } from '@/features/attachments';
import type { AttachmentResponse } from '@/shared/api';
import type { SortDirection } from '@/shared/ui/sort-select.types.ts';

type UploadSortField = 'name' | 'date';

function sortAttachments(
  items: AttachmentResponse[],
  field: UploadSortField,
  direction: SortDirection,
): AttachmentResponse[] {
  return [...items].sort((a, b) => {
    let cmp: number;
    if (field === 'date') {
      const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
      cmp = aTime - bTime;
    } else {
      cmp = a.filename.localeCompare(b.filename);
    }
    return direction === 'asc' ? cmp : -cmp;
  });
}

function buildUploadedTabItems({
  rawItems,
  categoryFilter,
  categoryById,
  sortField,
  sortDirection,
}: {
  readonly rawItems: readonly AttachmentResponse[];
  readonly categoryFilter: DocumentCategory | null;
  readonly categoryById: ReadonlyMap<string, DocumentCategory | null>;
  readonly sortField: UploadSortField;
  readonly sortDirection: SortDirection;
}): AttachmentResponse[] {
  const filteredItems: AttachmentResponse[] = [];
  for (const item of rawItems) {
    if (categoryFilter === null || categoryById.get(item.id) === categoryFilter) {
      filteredItems.push(item);
    }
  }

  return sortAttachments(filteredItems, sortField, sortDirection);
}

function useUploadedTabDocuments({
  rawItems,
  categoryFilter,
  sortField,
  sortDirection,
}: {
  readonly rawItems: readonly AttachmentResponse[];
  readonly categoryFilter: DocumentCategory | null;
  readonly sortField: UploadSortField;
  readonly sortDirection: SortDirection;
}): {
  sortedItems: AttachmentResponse[];
  totalItems: number;
} {
  const categoryById = new Map<string, DocumentCategory | null>();
  for (const item of rawItems) {
    categoryById.set(item.id, loadCategory(item.id));
  }

  const sortedItems = buildUploadedTabItems({
    rawItems,
    categoryFilter,
    categoryById,
    sortField,
    sortDirection,
  });

  const totalItems = categoryFilter ? sortedItems.length : rawItems.length;
  return { sortedItems, totalItems };
}

export type { UploadSortField };
export { useUploadedTabDocuments };
