import { type Span, SpanStatusCode, trace } from '@opentelemetry/api';
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { BFF_MAX_RESPONSE_BYTES, BFF_TIMEOUT_MS } from './constants';
import { app } from './index';
import {
  buildExecutionCtx,
  buildRequest,
  CROSS_ORIGIN_REDIRECT,
  EMPTY_RESPONSE,
  HTTP_INTERNAL_SERVER_ERROR,
  HTTP_OK,
  installCacheStub,
  type MockCache,
  SAMPLE_LISTINGS,
  TEST_ENV,
} from './index-test-support';

vi.mock('@hono/otel', () => ({
  httpInstrumentationMiddleware: () => async (_c: unknown, next: () => Promise<void>) => {
    await next();
  },
}));

vi.mock('@microlabs/otel-cf-workers', () => ({
  instrument: <T>(honoApp: T) => honoApp,
}));

let fetchMock: Mock;
let cache: MockCache;

beforeEach(() => {
  cache = installCacheStub();
  fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(SAMPLE_LISTINGS), {
      status: HTTP_OK,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('auth-listings error handling and CORS', () => {
  it('returns empty response with no-cache when BFF returns non-OK', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response('internal error', { status: HTTP_INTERNAL_SERVER_ERROR }),
    );

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, buildExecutionCtx());

    expect(res.status).toBe(HTTP_OK);
    expect(res.headers.get('Cache-Control')).toBe('no-cache');
    expect(await res.json()).toEqual(EMPTY_RESPONSE);
    expect(cache.put).not.toHaveBeenCalled();
  });

  it('returns empty response with no-cache on BFF network failure', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('network down'));

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, buildExecutionCtx());

    expect(res.status).toBe(HTTP_OK);
    expect(res.headers.get('Cache-Control')).toBe('no-cache');
    expect(await res.json()).toEqual(EMPTY_RESPONSE);
    expect(cache.put).not.toHaveBeenCalled();
  });

  it('never forwards the BFF secret to a cross-origin redirect target', async () => {
    const secretsReceivedByOrigin = new Map<string, string | null>();
    fetchMock.mockImplementationOnce((input: URL | RequestInfo, init?: RequestInit) => {
      const sourceOrigin = new URL(String(input)).origin;
      const secret = new Headers(init?.headers).get('X-Auth-Listings-Secret');
      secretsReceivedByOrigin.set(sourceOrigin, secret);

      // Model the platform's default redirect behavior: absent redirect:"error", the
      // redirected request retains the application-specific credential header.
      if (init?.redirect !== 'error') {
        secretsReceivedByOrigin.set(CROSS_ORIGIN_REDIRECT, secret);
        return new Response(JSON.stringify(SAMPLE_LISTINGS), { status: HTTP_OK });
      }
      throw new TypeError('Cross-origin redirect rejected');
    });

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, buildExecutionCtx());

    expect(secretsReceivedByOrigin.get(TEST_ENV.BFF_ORIGIN)).toBe(TEST_ENV.AUTH_LISTINGS_SECRET);
    expect(secretsReceivedByOrigin.has(CROSS_ORIGIN_REDIRECT)).toBe(false);
    expect(await res.json()).toEqual(EMPTY_RESPONSE);
    expect(res.headers.get('Cache-Control')).toBe('no-cache');
  });

  const oversizedJson = JSON.stringify({
    ...SAMPLE_LISTINGS,
    ignored_padding: 'x'.repeat(BFF_MAX_RESPONSE_BYTES),
  });
  const invalidListing = {
    ...SAMPLE_LISTINGS,
    listings: [{ ...SAMPLE_LISTINGS.listings[0], required_skills: [42] }],
  };

  it.each([
    {
      name: 'declared oversized response',
      response: () =>
        new Response(JSON.stringify(SAMPLE_LISTINGS), {
          status: HTTP_OK,
          headers: { 'Content-Length': String(BFF_MAX_RESPONSE_BYTES + 1) },
        }),
    },
    {
      name: 'streamed oversized response',
      response: () =>
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller: ReadableStreamDefaultController<Uint8Array>): void {
              controller.enqueue(new TextEncoder().encode(oversizedJson));
              controller.close();
            },
          }),
          { status: HTTP_OK },
        ),
    },
    {
      name: 'listing with a non-string skill',
      response: () => new Response(JSON.stringify(invalidListing), { status: HTTP_OK }),
    },
    {
      name: 'payload for a different country',
      response: () =>
        new Response(JSON.stringify({ ...SAMPLE_LISTINGS, country: 'GBR' }), { status: HTTP_OK }),
    },
  ])('fails closed without caching a $name', async ({ response }) => {
    fetchMock.mockResolvedValueOnce(response());

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, buildExecutionCtx());

    expect(res.status).toBe(HTTP_OK);
    expect(res.headers.get('Cache-Control')).toBe('no-cache');
    expect(await res.json()).toEqual(EMPTY_RESPONSE);
    expect(cache.put).not.toHaveBeenCalled();
  });

  it('enforces the BFF timeout while waiting for both headers and body', async () => {
    vi.useFakeTimers();
    const abortedPhases: string[] = [];

    try {
      for (const phase of ['headers', 'body'] as const) {
        fetchMock.mockImplementationOnce((_input: URL | RequestInfo, init?: RequestInit) => {
          const signal = init?.signal;
          if (!signal) {
            throw new Error('Expected worker fetch to provide an abort signal');
          }

          if (phase === 'headers') {
            return new Promise<Response>((_resolve, reject) => {
              signal.addEventListener(
                'abort',
                () => {
                  abortedPhases.push(phase);
                  reject(signal.reason);
                },
                { once: true },
              );
            });
          }

          return Promise.resolve(
            new Response(
              new ReadableStream<Uint8Array>({
                start(controller: ReadableStreamDefaultController<Uint8Array>): void {
                  signal.addEventListener(
                    'abort',
                    () => {
                      abortedPhases.push(phase);
                      controller.error(signal.reason);
                    },
                    { once: true },
                  );
                },
              }),
              { status: HTTP_OK },
            ),
          );
        });

        const responsePromise = app.fetch(
          buildRequest({ country: 'US' }),
          TEST_ENV,
          buildExecutionCtx(),
        );
        await vi.advanceTimersByTimeAsync(BFF_TIMEOUT_MS);
        const res = await responsePromise;

        expect(res.headers.get('Cache-Control')).toBe('no-cache');
        expect(await res.json()).toEqual(EMPTY_RESPONSE);
      }
    } finally {
      vi.useRealTimers();
    }

    expect(abortedPhases).toEqual(['headers', 'body']);
    expect(cache.put).not.toHaveBeenCalled();
  });

  it('redacts raw upstream exception details from logs and spans', async () => {
    const sensitiveDetail = 'credential=raw-secret-marker';
    const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    const span = {
      setAttribute: vi.fn(),
      setStatus: vi.fn(),
      recordException: vi.fn(),
      spanContext: () => ({ traceId: 'test-trace-id', spanId: 'test-span-id' }),
    };
    vi.spyOn(trace, 'getActiveSpan').mockReturnValue(span as unknown as Span);
    fetchMock.mockRejectedValueOnce(new Error(`upstream failed: ${sensitiveDetail}`));

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, buildExecutionCtx());

    expect(await res.json()).toEqual(EMPTY_RESPONSE);
    expect(consoleSpy.mock.calls.flat().join('\n')).not.toContain(sensitiveDetail);
    expect(span.setStatus).toHaveBeenCalledWith({
      code: SpanStatusCode.ERROR,
      message: 'BFF fetch failed',
    });
    expect(span.recordException).not.toHaveBeenCalled();
  });

  it('reflects allowed CORS origin', async () => {
    const res = await app.fetch(
      buildRequest({
        country: 'US',
        origin: 'https://nohiki.dev',
      }),
      TEST_ENV,
      buildExecutionCtx(),
    );

    expect(res.headers.get('Access-Control-Allow-Origin')).toBe('https://nohiki.dev');
  });

  it('omits CORS allow-origin for disallowed origins', async () => {
    const res = await app.fetch(
      buildRequest({
        country: 'US',
        origin: 'https://evil.example.com',
      }),
      TEST_ENV,
      buildExecutionCtx(),
    );

    expect(res.headers.get('Access-Control-Allow-Origin')).not.toBe('https://evil.example.com');
  });
});
