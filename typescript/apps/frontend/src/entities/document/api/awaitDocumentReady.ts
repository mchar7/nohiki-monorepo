import { getSafeGeneratedDocumentUrl } from '@/shared/lib/index.ts';
import { getDocumentEventStream } from './documentEventStream.ts';

const DEFAULT_TIMEOUT_MS = 300_000;

interface DocumentReadyResult {
  downloadUrl: string;
  status: string;
}

/**
 * Returns a promise that resolves when a specific document generation
 * request reaches a terminal state (completed or failed).
 *
 * Subscribes to the request-scoped SSE stream and resolves or rejects on its terminal event.
 */
export function awaitDocumentReady(
  requestId: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<DocumentReadyResult> {
  return new Promise<DocumentReadyResult>((resolve, reject) => {
    const stream = getDocumentEventStream(requestId);
    let settled = false;

    const timer = setTimeout((): void => {
      if (!settled) {
        settled = true;
        unsubscribe();
        reject(new Error(`Document generation timed out after ${timeoutMs}ms`));
      }
    }, timeoutMs);

    const unsubscribe = stream.subscribe((event: MessageEvent): void => {
      const data = JSON.parse(event.data) as {
        request_id: string;
        status: string;
        storage_key?: string;
        error_message?: string;
      };

      if (data.request_id !== requestId) {
        return;
      }

      if (data.status === 'completed' && data.storage_key) {
        const downloadUrl = getSafeGeneratedDocumentUrl(data.storage_key, window.location.origin);
        settled = true;
        clearTimeout(timer);
        unsubscribe();
        if (downloadUrl) {
          resolve({ downloadUrl, status: data.status });
        } else {
          reject(new Error('Document generation failed'));
        }
      } else if (data.status === 'failed') {
        settled = true;
        clearTimeout(timer);
        unsubscribe();
        reject(new Error(data.error_message ?? 'Document generation failed'));
      }
    });
  });
}
