import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { JSX, ReactNode } from 'react';
import { afterAll, beforeEach, describe, expect, vi } from 'vitest';
import { getDocumentEventStream, resetDocumentEventStream } from '@/entities/document/index.ts';
import { nonNull } from '@/shared/test-utils';
import { MockEventSource } from '@/test/mocks/MockEventSource';
import { useDocumentSSE } from './useDocumentSSE';

vi.stubGlobal('EventSource', MockEventSource);

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function createWrapper(): ({ children }: { children: ReactNode }) => JSX.Element {
  const queryClient = createTestQueryClient();
  return function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return QueryClientProvider({ client: queryClient, children }) as JSX.Element;
  };
}

afterAll(() => {
  vi.unstubAllGlobals();
});

describe('useDocumentSSE initial state', () => {
  beforeEach(() => {
    resetDocumentEventStream();
    MockEventSource.reset();
  });

  test('returns idle status when requestId is null', () => {
    const { result } = renderHook(() => useDocumentSSE(null), { wrapper: createWrapper() });
    expect(result.current.status).toBe('idle');
    expect(result.current.downloadUrl).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.isConnected).toBe(false);
  });

  test('opens the exact encoded per-request endpoint without URL credentials', () => {
    renderHook(() => useDocumentSSE('req/with spaces'), { wrapper: createWrapper() });

    expect(MockEventSource.instances).toHaveLength(1);
    const instance = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');
    expect(instance.url).toBe('/api/documents/req%2Fwith%20spaces/events');
    expect(new URL(instance.url, 'https://app.nohiki.test').search).toBe('');
    expect(instance.url).not.toContain('token');
    expect(getDocumentEventStream('req/with spaces').subscriberCount).toBe(1);
  });

  test('isolates native streams by request while sharing subscribers for one request', () => {
    renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    renderHook(() => useDocumentSSE('req-2'), { wrapper: createWrapper() });

    expect(MockEventSource.instances.map(({ url }) => url)).toEqual([
      '/api/documents/req-1/events',
      '/api/documents/req-2/events',
    ]);
    expect(getDocumentEventStream('req-1').subscriberCount).toBe(2);
    expect(getDocumentEventStream('req-2').subscriberCount).toBe(1);
  });

  test('closes the expired-session stream and creates a fresh credentialed connection', () => {
    renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    const expired = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');

    resetDocumentEventStream('req-1');
    expect(expired.readyState).toBe(MockEventSource.CLOSED);

    renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    const refreshed = nonNull(MockEventSource.instances[1], 'Fresh EventSource was not created');
    expect(refreshed).not.toBe(expired);
    expect(refreshed.url).toBe('/api/documents/req-1/events');
    expect(refreshed.withCredentials).toBe(true);
  });
});

describe('useDocumentSSE event handling', () => {
  beforeEach(() => {
    resetDocumentEventStream();
    MockEventSource.reset();
  });

  test('sets status to connected and downloadUrl on completed event for matching requestId', () => {
    const { result } = renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    const instance = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');
    act(() => {
      instance.simulateOpen();
      instance.simulateEvent(
        'document_status',
        JSON.stringify({
          request_id: 'req-1',
          status: 'completed',
          storage_key: 'rendered/req-1/output.pdf',
        }),
      );
    });
    expect(result.current.status).toBe('completed');
    expect(result.current.downloadUrl).toBe(
      new URL('/rendered/req-1/output.pdf', window.location.origin).href,
    );
    expect(result.current.error).toBeNull();
  });

  test.each([
    'javascript:alert(1)',
    'data:text/html,unsafe',
    'https://user:password@example.com/output.pdf',
    '//example.com/output.pdf',
    'https://[invalid',
  ])('uses the existing failed UI state for unsafe URL %s', (storageKey) => {
    const { result } = renderHook(() => useDocumentSSE('req-unsafe'), {
      wrapper: createWrapper(),
    });
    const instance = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');

    act(() => {
      instance.simulateEvent(
        'document_status',
        JSON.stringify({
          request_id: 'req-unsafe',
          status: 'completed',
          storage_key: storageKey,
        }),
      );
    });

    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Document generation failed');
    expect(result.current.downloadUrl).toBeNull();
  });

  test('sets error on failed event for matching requestId', () => {
    const { result } = renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    const instance = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');
    act(() => {
      instance.simulateOpen();
      instance.simulateEvent(
        'document_status',
        JSON.stringify({ request_id: 'req-1', status: 'failed', error_message: 'Render failed' }),
      );
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Render failed');
    expect(result.current.downloadUrl).toBeNull();
  });

  test('ignores events for non-matching requestId', () => {
    const { result } = renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    const instance = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');
    act(() => {
      instance.simulateOpen();
      instance.simulateEvent(
        'document_status',
        JSON.stringify({
          request_id: 'req-OTHER',
          status: 'completed',
          storage_key: 'docs/other.pdf',
        }),
      );
    });
    expect(result.current.status).toBe('connecting');
    expect(result.current.downloadUrl).toBeNull();
  });
});

describe('useDocumentSSE side effects', () => {
  beforeEach(() => {
    resetDocumentEventStream();
    MockEventSource.reset();
  });

  test('calls queryClient.invalidateQueries on completed event', () => {
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const wrapper = ({ children }: { children: ReactNode }): JSX.Element =>
      QueryClientProvider({ client: queryClient, children }) as JSX.Element;

    renderHook(() => useDocumentSSE('req-1'), { wrapper });
    const instance = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');
    act(() => {
      instance.simulateOpen();
      instance.simulateEvent(
        'document_status',
        JSON.stringify({
          request_id: 'req-1',
          status: 'completed',
          storage_key: 'rendered/req-1/output.pdf',
        }),
      );
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ predicate: expect.any(Function) });
  });

  test('manual disconnect closes its request stream and ignores later events', () => {
    const { result } = renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    const instance = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');
    instance.simulateOpen();

    act(() => result.current.disconnect());

    expect(result.current.status).toBe('idle');
    expect(getDocumentEventStream('req-1').subscriberCount).toBe(0);
    expect(instance.readyState).toBe(MockEventSource.CLOSED);

    act(() => {
      instance.simulateEvent(
        'document_status',
        JSON.stringify({
          request_id: 'req-1',
          status: 'completed',
          storage_key: 'rendered/req-1/late.pdf',
        }),
      );
    });

    expect(result.current.status).toBe('idle');
    expect(result.current.downloadUrl).toBeNull();
  });

  test('terminal event unsubscribes once and ignores a later terminal duplicate', () => {
    const { result } = renderHook(() => useDocumentSSE('req-1'), { wrapper: createWrapper() });
    const instance = nonNull(MockEventSource.instances[0], 'MockEventSource was not created');

    act(() => {
      instance.simulateEvent(
        'document_status',
        JSON.stringify({
          request_id: 'req-1',
          status: 'completed',
          storage_key: 'rendered/req-1/final.pdf',
        }),
      );
    });

    expect(result.current.status).toBe('completed');
    expect(getDocumentEventStream('req-1').subscriberCount).toBe(0);
    expect(instance.readyState).toBe(MockEventSource.CLOSED);

    act(() => {
      instance.simulateEvent(
        'document_status',
        JSON.stringify({
          request_id: 'req-1',
          status: 'failed',
          error_message: 'late duplicate',
        }),
      );
    });

    expect(result.current.status).toBe('completed');
    expect(result.current.error).toBeNull();
  });

  test('unsubscribes on cleanup (unmount)', () => {
    const { unmount } = renderHook(() => useDocumentSSE('req-1'), {
      wrapper: createWrapper(),
    });
    expect(getDocumentEventStream('req-1').subscriberCount).toBe(1);
    unmount();
    expect(getDocumentEventStream('req-1').subscriberCount).toBe(0);
  });
});
