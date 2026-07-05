import type { AttachmentResponse, DocumentStatusResponse } from '@/shared/api';

/** Discriminated union representing either an uploaded attachment or a generated document. */
type UnifiedDocument =
  | { type: 'uploaded'; data: AttachmentResponse }
  | { type: 'generated'; data: DocumentStatusResponse };

export type { UnifiedDocument };
