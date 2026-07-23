import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { MockEventSource } from '@/test/mocks/MockEventSource';
import { awaitDocumentReady } from './awaitDocumentReady.ts';
import { getDocumentEventStream, resetDocumentEventStream } from './documentEventStream.ts';

function emitDocumentStatus(data: object): void {
  const [instance] = MockEventSource.instances;
  instance?.simulateEvent('document_status', JSON.stringify(data));
}

beforeEach(() => {
  MockEventSource.reset();
  resetDocumentEventStream();
  vi.stubGlobal('EventSource', MockEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('awaitDocumentReady resolution', () => {
  test('resolves with a credential-free HTTPS download URL', async () => {
    const promise = awaitDocumentReady('req-123');

    emitDocumentStatus({
      request_id: 'req-123',
      status: 'completed',
      storage_key: 'https://storage.example.com/doc.pdf?signature=abc',
    });

    await expect(promise).resolves.toEqual({
      downloadUrl: 'https://storage.example.com/doc.pdf?signature=abc',
      status: 'completed',
    });
  });

  test.each([
    'javascript:alert(1)',
    'data:text/html,unsafe',
    'https://user:password@storage.example.com/doc.pdf',
    '//storage.example.com/doc.pdf',
    'https://storage.example.com/doc.pdf\nunsafe',
    'https://[invalid',
  ])('rejects unsafe completed storage key %s', async (storageKey) => {
    const promise = awaitDocumentReady('req-unsafe');

    emitDocumentStatus({
      request_id: 'req-unsafe',
      status: 'completed',
      storage_key: storageKey,
    });

    await expect(promise).rejects.toThrow('Document generation failed');
  });

  test('rejects through the existing error path when the generated URL is unavailable', async () => {
    const promise = awaitDocumentReady('req-missing');

    emitDocumentStatus({
      request_id: 'req-missing',
      status: 'failed',
      error_message: 'Generated document is unavailable',
    });

    await expect(promise).rejects.toThrow('Generated document is unavailable');
  });

  test('rejects with error message when failed event arrives', async () => {
    const promise = awaitDocumentReady('req-456');

    emitDocumentStatus({
      request_id: 'req-456',
      status: 'failed',
      error_message: 'Render timeout exceeded',
    });

    await expect(promise).rejects.toThrow('Render timeout exceeded');
  });

  test('falls back to generic message when failed event has no error_message', async () => {
    const promise = awaitDocumentReady('req-789');

    emitDocumentStatus({ request_id: 'req-789', status: 'failed' });

    await expect(promise).rejects.toThrow('Document generation failed');
  });
});

describe('awaitDocumentReady edge cases', () => {
  test('ignores events for other requestIds', async () => {
    const promise = awaitDocumentReady('req-target');

    emitDocumentStatus({
      request_id: 'req-other',
      status: 'completed',
      storage_key: 'https://storage.example.com/wrong.pdf',
    });

    let settled = false;
    promise
      .then(() => {
        settled = true;
      })
      .catch(() => {
        settled = true;
      });

    await Promise.resolve();
    expect(settled).toBe(false);

    emitDocumentStatus({
      request_id: 'req-target',
      status: 'completed',
      storage_key: 'https://storage.example.com/correct.pdf',
    });

    const result = await promise;
    expect(result.downloadUrl).toBe('https://storage.example.com/correct.pdf');
  });

  const TIMEOUT_MS = 100;
  const ADVANCE_MS = 150;
  test('rejects on timeout when no terminal event arrives', async () => {
    vi.useFakeTimers();

    const promise = awaitDocumentReady('req-timeout', TIMEOUT_MS);

    vi.advanceTimersByTime(ADVANCE_MS);

    await expect(promise).rejects.toThrow(`Document generation timed out after ${TIMEOUT_MS}ms`);
  });

  test('unsubscribes from manager after settlement', async () => {
    const promise = awaitDocumentReady('req-cleanup');

    emitDocumentStatus({
      request_id: 'req-cleanup',
      status: 'completed',
      storage_key: 'https://storage.example.com/doc.pdf',
    });
    await promise;

    expect(getDocumentEventStream('req-cleanup').subscriberCount).toBe(0);
  });
});
