import { type Mock, vi } from 'vitest';
import type { AuthListingsResponse, WorkerEnv } from './types';

export const HTTP_OK = 200;
export const HTTP_INTERNAL_SERVER_ERROR = 500;
export const FETCH_CALLS_ON_MISS = 1;
export const CROSS_ORIGIN_REDIRECT = 'https://redirect-attacker.test';

export const NON_EMPTY_CACHE_CONTROL_S_MAXAGE_RE = /s-maxage=10800/u;
export const NON_EMPTY_CACHE_CONTROL_SWR_RE = /stale-while-revalidate=259200/u;
export const EMPTY_CACHE_CONTROL_S_MAXAGE_RE = /s-maxage=300/u;

export const TEST_ENV: WorkerEnv = {
  BFF_ORIGIN: 'https://bff.test',
  AUTH_LISTINGS_SECRET: 'test-secret',
  ALLOWED_ORIGINS: 'https://nohiki.dev,https://app.nohiki.dev',
  OTEL_EXPORTER_OTLP_ENDPOINT: 'https://otel.test',
  OTEL_EXPORTER_AUTH_TOKEN: 'otel-token',
};

export const SAMPLE_LISTINGS: AuthListingsResponse = {
  listings: [
    {
      title: 'Senior Python Engineer',
      company_name: 'Acme',
      location_raw: 'Remote',
      work_arrangement: 'REMOTE',
      required_skills: ['Python'],
      posted_at: '2026-04-16T00:00:00Z',
      language: 'en',
    },
  ],
  country: 'USA',
};

export const EMPTY_RESPONSE: AuthListingsResponse = { listings: [], country: 'USA' };

export interface MockCache {
  match: Mock;
  put: Mock;
}

export function installCacheStub(): MockCache {
  const mockCache: MockCache = {
    match: vi.fn().mockResolvedValue(undefined),
    put: vi.fn().mockResolvedValue(undefined),
  };
  vi.stubGlobal('caches', { default: mockCache });
  return mockCache;
}

interface BuildRequestOptions {
  readonly path?: string;
  readonly country?: string;
  readonly origin?: string;
  readonly acceptLanguage?: string;
  readonly lang?: string;
}

export function buildRequest(options: BuildRequestOptions): Request {
  const path = options.path ?? '/auth-listings';
  let url = `https://worker.test${path}`;
  if (options.lang) {
    url += `?lang=${encodeURIComponent(options.lang)}`;
  }

  const headers: Record<string, string> = {};
  if (options.origin !== undefined) {
    headers.Origin = options.origin;
  }
  if (options.acceptLanguage !== undefined) {
    headers['Accept-Language'] = options.acceptLanguage;
  }

  let cf: { country?: string } = {};
  if (options.country !== undefined) {
    cf = { country: options.country };
  }
  return Object.assign(new Request(url, { headers }), { cf });
}

class TestSpan implements Span {
  readonly isTraced = false;

  setAttribute(): void {
    void this.isTraced;
  }

  end(): void {
    void this.isTraced;
  }
}

const testTracing: Tracing = {
  enterSpan<T, A extends unknown[]>(
    _name: string,
    callback: (span: Span, ...args: A) => T,
    ...args: A
  ): T {
    return callback(new TestSpan(), ...args);
  },
  startActiveSpan<T, A extends unknown[]>(
    _name: string,
    callback: (span: Span, ...args: A) => T,
    ...args: A
  ): T {
    return callback(new TestSpan(), ...args);
  },
  Span: TestSpan,
};

export function buildExecutionCtx(): ExecutionContext {
  return {
    waitUntil: vi.fn(),
    passThroughOnException: vi.fn(),
    exports: {},
    props: {},
    tracing: testTracing,
  };
}

export function buildExpectedBffUrl(country: string, lang?: string): string {
  const expectedUrl = new URL('/api/v1/auth-listings', TEST_ENV.BFF_ORIGIN);
  expectedUrl.searchParams.set('country', country);
  if (lang) {
    expectedUrl.searchParams.set('lang', lang);
  }
  return expectedUrl.toString();
}

export function getCacheControl(response: Response): string {
  return response.headers.get('Cache-Control') ?? '';
}
