import { httpInstrumentationMiddleware } from '@hono/otel';
import { instrument, type ResolveConfigFn, type Trigger } from '@microlabs/otel-cf-workers';
import { SpanStatusCode, trace } from '@opentelemetry/api';
import type { Context } from 'hono';
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { buildCacheHeaders, buildCacheKey } from './cache';
import {
  BFF_TIMEOUT_MS,
  CACHE_EMPTY_RESPONSE_SECONDS,
  WORKER_SERVICE_NAME,
  WORKER_SERVICE_VERSION,
} from './constants';
import { resolveCountry } from './geo';
import { workerLogger } from './logger';
import type { AuthListingsResponse, WorkerEnv } from './types';
import { readAuthListingsResponse } from './upstream-response';

type AppContext = Context<{ Bindings: WorkerEnv }>;

const HTTP_OK = 200;
const SPAN_ATTR_COUNTRY = 'country';
const SPAN_ATTR_CACHE_STATUS = 'cache_status';
const SPAN_ATTR_UPSTREAM_STATUS_CODE = 'upstream_status_code';

const allowedOriginsCache: Map<string, ReadonlySet<string>> = new Map();

/** Raw Hono app exported for test access; the default export below wraps it with OTel instrumentation. */
const app: Hono<{ Bindings: WorkerEnv }> = new Hono<{ Bindings: WorkerEnv }>();

/** Parse and cache the comma-delimited allowed-origins binding per isolate. */
function getAllowedOrigins(env: WorkerEnv): ReadonlySet<string> {
  const cached = allowedOriginsCache.get(env.ALLOWED_ORIGINS);
  if (cached !== undefined) {
    return cached;
  }

  const origins = new Set(env.ALLOWED_ORIGINS.split(',').map((s) => s.trim()));
  allowedOriginsCache.set(env.ALLOWED_ORIGINS, origins);
  return origins;
}

app.use(
  '*',
  httpInstrumentationMiddleware({
    serviceName: WORKER_SERVICE_NAME,
    serviceVersion: WORKER_SERVICE_VERSION,
  }),
);

app.use(
  '*',
  cors({
    origin: (origin: string, c: AppContext) => {
      const origins = getAllowedOrigins(c.env);
      if (origins.has(origin)) {
        return origin;
      }
      return '';
    },
    maxAge: 86_400,
  }),
);

const LANG_PRIMARY_SUBTAG_RE = /^[a-z]{2,3}$/u;
const LANG_DELIMITER_RE = /[-_,;]/u;

/**
 * Normalize a language tag to its lowercase primary subtag.
 * "en-US" → "en", "zh-Hant-TW" → "zh", malformed → undefined.
 * Constrains cache cardinality to the BCP-47 primary language set.
 */
function normalizeLang(raw: string | undefined | null): string | undefined {
  if (!raw) {
    return;
  }
  const primary = raw.trim().split(LANG_DELIMITER_RE)[0]?.toLowerCase();
  if (!(primary && LANG_PRIMARY_SUBTAG_RE.test(primary))) {
    return;
  }
  return primary;
}

/** Extract language from query param or Accept-Language header, normalized to primary subtag. */
function extractLang(ctx: AppContext): string | undefined {
  return normalizeLang(ctx.req.query('lang')) ?? normalizeLang(ctx.req.header('Accept-Language'));
}

/** Build a fallback error response with no-cache headers. */
function buildErrorResponse(ctx: AppContext, country: string): Response {
  return ctx.json({ listings: [], country } satisfies AuthListingsResponse, HTTP_OK, {
    'Cache-Control': 'no-cache',
  });
}

/** Promote a span to error status without exporting exception contents. */
function markSpanError(message: string): void {
  trace.getActiveSpan()?.setStatus({ code: SpanStatusCode.ERROR, message });
}

/** Build optional OTLP exporter headers, omitting auth when not configured. */
function buildOtelExporterHeaders(token: string | undefined): Record<string, string> | undefined {
  if (!token) {
    return;
  }
  return { Authorization: `Bearer ${token}` };
}

/** Attach optional exporter headers without introducing exact-optional-property errors. */
function buildOtelExporter(
  token: string | undefined,
  url: string,
): { url: string; headers?: Record<string, string> } {
  const headers = buildOtelExporterHeaders(token);
  if (!headers) {
    return { url };
  }
  return { url, headers };
}

/** Fetch and validate listings under one timeout covering headers and body. */
async function fetchFromBff(
  ctx: AppContext,
  country: string,
  lang: string | undefined,
): Promise<{ response: Response; data: AuthListingsResponse | undefined }> {
  const bffUrl = new URL('/api/v1/auth-listings', ctx.env.BFF_ORIGIN);
  bffUrl.searchParams.set('country', country);
  if (lang) {
    bffUrl.searchParams.set('lang', lang);
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), BFF_TIMEOUT_MS);

  try {
    const response = await fetch(bffUrl, {
      signal: controller.signal,
      redirect: 'error',
      headers: {
        'X-Auth-Listings-Secret': ctx.env.AUTH_LISTINGS_SECRET,
        Accept: 'application/json',
      },
    });
    if (!response.ok) {
      return { response, data: undefined };
    }

    return { response, data: await readAuthListingsResponse(response, country) };
  } finally {
    controller.abort();
    clearTimeout(timeoutId);
  }
}

/** Build Cache-Control headers based on whether the response has listings. */
function buildResponseCacheHeaders(hasListings: boolean): Record<string, string> {
  if (hasListings) {
    return buildCacheHeaders();
  }
  return { 'Cache-Control': `public, s-maxage=${CACHE_EMPTY_RESPONSE_SECONDS}` };
}

/** Cache a successful BFF response with appropriate TTL. */
function cacheResponse(ctx: AppContext, data: AuthListingsResponse, key: string): Response {
  const response = ctx.json(data, HTTP_OK, buildResponseCacheHeaders(data.listings.length > 0));
  const cacheWrite = caches.default
    .put(new Request(key), response.clone())
    .catch(() =>
      workerLogger.warn('Cache write failed', { country: data.country, cache: 'error' }),
    );
  ctx.executionCtx.waitUntil(cacheWrite);
  return response;
}

app.get('/auth-listings', async (c) => {
  const country = resolveCountry(c.req.raw.cf?.country as string | undefined);
  const lang = extractLang(c);

  const span = trace.getActiveSpan();
  span?.setAttribute(SPAN_ATTR_COUNTRY, country);

  const cacheKey = buildCacheKey(country, lang);
  const cache = caches.default;

  let cached: Response | undefined;
  try {
    cached = await cache.match(new Request(cacheKey));
  } catch {
    span?.setAttribute(SPAN_ATTR_CACHE_STATUS, 'error');
    workerLogger.warn('Cache read failed', { country, cache: 'error' });
  }
  if (cached) {
    span?.setAttribute(SPAN_ATTR_CACHE_STATUS, 'hit');
    workerLogger.info('Cache hit', { country, cache: 'hit' });
    return new Response(cached.body, cached);
  }

  span?.setAttribute(SPAN_ATTR_CACHE_STATUS, 'miss');
  workerLogger.info('Cache miss, fetching from BFF', { country, cache: 'miss' });

  try {
    const { response: bffResponse, data } = await fetchFromBff(c, country, lang);

    if (!bffResponse.ok) {
      span?.setAttribute(SPAN_ATTR_UPSTREAM_STATUS_CODE, bffResponse.status);
      markSpanError(`BFF returned ${bffResponse.status}`);
      workerLogger.warn('BFF returned non-OK status', {
        country,
        extra: { status: bffResponse.status },
      });
      return buildErrorResponse(c, country);
    }

    if (!data) {
      throw new Error('BFF response body was unavailable');
    }
    return cacheResponse(c, data, cacheKey);
  } catch {
    markSpanError('BFF fetch failed');
    workerLogger.error('BFF fetch failed', { country });
    return buildErrorResponse(c, country);
  }
});

app.onError((_err, c) => {
  markSpanError('Unhandled worker error');
  workerLogger.error('Unhandled worker error');
  return c.json({ listings: [], country: '' } satisfies AuthListingsResponse, HTTP_OK, {
    'Cache-Control': 'no-cache',
  });
});

const otelConfig: ResolveConfigFn = (env: WorkerEnv, _trigger: Trigger) => ({
  exporter: buildOtelExporter(env.OTEL_EXPORTER_AUTH_TOKEN, env.OTEL_EXPORTER_OTLP_ENDPOINT),
  service: { name: WORKER_SERVICE_NAME, version: WORKER_SERVICE_VERSION },
});

export { app, buildOtelExporterHeaders };

export default instrument(app, otelConfig);
