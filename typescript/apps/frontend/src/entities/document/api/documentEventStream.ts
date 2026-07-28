import { SseStreamManager } from '@/shared/api/index.ts';
import { registerSessionReset } from '@/shared/lib/index.ts';

const DOCUMENT_STATUS_EVENT = 'document_status';

const streams = new Map<string, SseStreamManager>();

/** Return the shared native EventSource manager for one document request. */
export function getDocumentEventStream(requestId: string): SseStreamManager {
  const existing = streams.get(requestId);
  if (existing) {
    return existing;
  }

  const stream = new SseStreamManager({
    url: `/api/documents/${encodeURIComponent(requestId)}/events`,
    eventName: DOCUMENT_STATUS_EVENT,
  });
  streams.set(requestId, stream);
  return stream;
}

/** Tear down one request stream, or every stream for test/app cleanup. */
export function resetDocumentEventStream(requestId?: string): void {
  if (requestId !== undefined) {
    streams.get(requestId)?.destroy();
    streams.delete(requestId);
    return;
  }

  for (const stream of streams.values()) {
    stream.destroy();
  }
  streams.clear();
}

registerSessionReset(resetDocumentEventStream);
