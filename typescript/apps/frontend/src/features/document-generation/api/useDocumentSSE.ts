import { type QueryClient, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { getDocumentEventStream } from '@/entities/document/index.ts';
import { invalidateByPath } from '@/shared/api/index.ts';
import { getSafeGeneratedDocumentUrl } from '@/shared/lib/index.ts';

type SSEStatus = 'idle' | 'connecting' | 'connected' | 'completed' | 'failed';

interface DocumentSSEResult {
  status: SSEStatus;
  downloadUrl: string | null;
  error: string | null;
  progress: number;
  disconnect: () => void;
  isConnected: boolean;
}

interface DocumentStatusEvent {
  request_id: string;
  status: string;
  storage_key?: string;
  error_message?: string;
  progress?: number;
}

interface DocumentStatusSetters {
  setStatus: (status: SSEStatus) => void;
  setDownloadUrl: (url: string | null) => void;
  setError: (error: string | null) => void;
  setProgress: (progress: number) => void;
}

/** Applies a "completed" event: resolves the download URL or falls back to a failure state. */
function handleCompletedEvent(
  data: DocumentStatusEvent,
  setters: DocumentStatusSetters,
  queryClient: QueryClient,
): void {
  const downloadUrl = getSafeGeneratedDocumentUrl(data.storage_key, window.location.origin);
  if (!downloadUrl) {
    setters.setDownloadUrl(null);
    setters.setError('Document generation failed');
    setters.setStatus('failed');
    return;
  }
  setters.setDownloadUrl(downloadUrl);
  setters.setStatus('completed');
  invalidateByPath(queryClient, '/api/v1/documents').catch((_: unknown) => undefined);
}

/** Applies a "failed" event. */
function handleFailedEvent(data: DocumentStatusEvent, setters: DocumentStatusSetters): void {
  setters.setError(data.error_message ?? 'Unknown error');
  setters.setStatus('failed');
}

/** Routes a document status event to the matching state transition. */
function applyDocumentStatusEvent(
  data: DocumentStatusEvent,
  setters: DocumentStatusSetters,
  queryClient: QueryClient,
): void {
  setters.setStatus('connected');
  if (data.status === 'completed') {
    handleCompletedEvent(data, setters, queryClient);
  } else if (data.status === 'failed') {
    handleFailedEvent(data, setters);
  } else if (data.progress !== undefined) {
    setters.setProgress(data.progress);
  }
}

/** SSE-based real-time tracking of document generation progress. */
function useDocumentSSE(requestId: string | null): DocumentSSEResult {
  const [status, setStatus] = useState<SSEStatus>('idle');
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const queryClient = useQueryClient();
  const unsubscribeRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!requestId) {
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      setStatus('idle');
      return;
    }

    setStatus('connecting');

    const setters: DocumentStatusSetters = { setStatus, setDownloadUrl, setError, setProgress };

    let closeStream: () => void;

    const handler = (event: MessageEvent): void => {
      const data = JSON.parse(event.data) as DocumentStatusEvent;

      if (data.request_id !== requestId) {
        return;
      }

      applyDocumentStatusEvent(data, setters, queryClient);
      if (data.status === 'completed' || data.status === 'failed') {
        closeStream();
      }
    };

    const unsubscribe = getDocumentEventStream(requestId).subscribe(handler);
    let active = true;
    closeStream = (): void => {
      if (!active) {
        return;
      }
      active = false;
      unsubscribe();
      if (unsubscribeRef.current === closeStream) {
        unsubscribeRef.current = null;
      }
    };
    unsubscribeRef.current = closeStream;
    return closeStream;
  }, [requestId, queryClient]);

  const disconnect = (): void => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    setStatus('idle');
  };

  return {
    status,
    downloadUrl,
    error,
    progress,
    disconnect,
    isConnected: status === 'connected',
  };
}

export { useDocumentSSE };
