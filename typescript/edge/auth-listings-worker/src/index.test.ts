import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { app, buildOtelExporterHeaders } from './index';
import {
  buildExecutionCtx,
  buildExpectedBffUrl,
  buildRequest,
  EMPTY_CACHE_CONTROL_S_MAXAGE_RE,
  FETCH_CALLS_ON_MISS,
  getCacheControl,
  HTTP_OK,
  installCacheStub,
  type MockCache,
  NON_EMPTY_CACHE_CONTROL_S_MAXAGE_RE,
  NON_EMPTY_CACHE_CONTROL_SWR_RE,
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

function getFirstFetchUrl(): string {
  const [bffUrl] = fetchMock.mock.calls[0] ?? [];
  return String(bffUrl);
}

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

describe('auth-listings cache behavior', () => {
  it('returns cached response when cache hit, skipping BFF call', async () => {
    const cached = new Response(JSON.stringify(SAMPLE_LISTINGS), { status: HTTP_OK });
    cache.match.mockResolvedValueOnce(cached);

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, buildExecutionCtx());

    expect(res.status).toBe(HTTP_OK);
    expect(await res.json()).toEqual(SAMPLE_LISTINGS);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('fetches from BFF on cache miss and caches the response', async () => {
    const ctx = buildExecutionCtx();

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, ctx);

    expect(res.status).toBe(HTTP_OK);
    expect(fetchMock).toHaveBeenCalledTimes(FETCH_CALLS_ON_MISS);
    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(getFirstFetchUrl()).toBe(buildExpectedBffUrl('USA'));
    const headers = (init as RequestInit | undefined)?.headers as
      | Record<string, string>
      | undefined;
    expect(headers?.['X-Auth-Listings-Secret']).toBe('test-secret');
    expect(ctx.waitUntil).toHaveBeenCalledTimes(FETCH_CALLS_ON_MISS);
  });

  it('serves fresh BFF listings when the cache read fails', async () => {
    cache.match.mockRejectedValueOnce(new Error('cache read unavailable'));

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, buildExecutionCtx());

    expect(res.status).toBe(HTTP_OK);
    expect(await res.json()).toEqual(SAMPLE_LISTINGS);
    expect(fetchMock).toHaveBeenCalledTimes(FETCH_CALLS_ON_MISS);
    expect(cache.put).toHaveBeenCalledTimes(FETCH_CALLS_ON_MISS);
  });

  it('keeps the response successful and absorbs a background cache write failure', async () => {
    const ctx = buildExecutionCtx();
    cache.put.mockRejectedValueOnce(new Error('cache write unavailable'));

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, ctx);
    const cacheWrite = vi.mocked(ctx.waitUntil).mock.calls[0]?.[0];
    if (!cacheWrite) {
      throw new Error('Expected cache write task to be registered');
    }

    expect(res.status).toBe(HTTP_OK);
    expect(await res.json()).toEqual(SAMPLE_LISTINGS);
    await expect(cacheWrite).resolves.toBeUndefined();
  });
});

describe('auth-listings cache headers', () => {
  it('caches non-empty BFF responses with 3h s-maxage + stale-while-revalidate', async () => {
    const ctx = buildExecutionCtx();

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, ctx);

    const cacheControl = getCacheControl(res);
    expect(cacheControl).toMatch(NON_EMPTY_CACHE_CONTROL_S_MAXAGE_RE);
    expect(cacheControl).toMatch(NON_EMPTY_CACHE_CONTROL_SWR_RE);
    expect(ctx.waitUntil).toHaveBeenCalledTimes(FETCH_CALLS_ON_MISS);
  });

  it('caches empty BFF responses with short 5-min TTL (no SWR)', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ listings: [], country: 'USA' }), { status: HTTP_OK }),
    );

    const res = await app.fetch(buildRequest({ country: 'US' }), TEST_ENV, buildExecutionCtx());

    const cacheControl = getCacheControl(res);
    expect(cacheControl).toMatch(EMPTY_CACHE_CONTROL_S_MAXAGE_RE);
    expect(cacheControl).not.toContain('stale-while-revalidate');
  });
});

describe('auth-listings country resolution', () => {
  it('resolves country from request.cf (GB → GBR)', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ...SAMPLE_LISTINGS, country: 'GBR' }), { status: HTTP_OK }),
    );

    await app.fetch(buildRequest({ country: 'GB' }), TEST_ENV, buildExecutionCtx());

    expect(getFirstFetchUrl()).toBe(buildExpectedBffUrl('GBR'));
  });

  it('defaults to USA when request.cf.country is missing', async () => {
    await app.fetch(buildRequest({}), TEST_ENV, buildExecutionCtx());

    expect(getFirstFetchUrl()).toBe(buildExpectedBffUrl('USA'));
  });
});

describe('auth-listings language normalization', () => {
  it('normalizes Accept-Language to primary subtag ("en-US" → "en")', async () => {
    await app.fetch(
      buildRequest({ country: 'US', acceptLanguage: 'en-US,en;q=0.9' }),
      TEST_ENV,
      buildExecutionCtx(),
    );

    expect(getFirstFetchUrl()).toBe(buildExpectedBffUrl('USA', 'en'));
    expect(getFirstFetchUrl()).not.toContain('en-US');
  });

  it('drops malformed Accept-Language values', async () => {
    await app.fetch(
      buildRequest({ country: 'US', acceptLanguage: '123,zz-invalid' }),
      TEST_ENV,
      buildExecutionCtx(),
    );

    expect(getFirstFetchUrl()).toBe(buildExpectedBffUrl('USA'));
  });

  it('prefers ?lang query param over Accept-Language header', async () => {
    await app.fetch(
      buildRequest({ country: 'US', lang: 'FR', acceptLanguage: 'en-GB' }),
      TEST_ENV,
      buildExecutionCtx(),
    );

    expect(getFirstFetchUrl()).toBe(buildExpectedBffUrl('USA', 'fr'));
  });
});

describe('OTLP exporter config helpers', () => {
  it('builds bearer auth header when token is configured', () => {
    expect(buildOtelExporterHeaders('otel-token')).toEqual({ Authorization: 'Bearer otel-token' });
  });
  it('omits auth header when token is unset', () => {
    expect(buildOtelExporterHeaders(undefined)).toBeUndefined();
    expect(buildOtelExporterHeaders('')).toBeUndefined();
  });
});
