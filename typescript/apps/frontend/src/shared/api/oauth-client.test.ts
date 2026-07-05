import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import type { OAuthProvider } from './types.ts';

const {
  mockGet,
  mockDelete,
}: {
  mockGet: ReturnType<typeof vi.fn>;
  mockDelete: ReturnType<typeof vi.fn>;
} = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockDelete: vi.fn(),
}));

vi.mock('@/shared/api/client', () => ({
  fetchClient: { GET: mockGet, POST: vi.fn(), DELETE: mockDelete, PATCH: vi.fn(), PUT: vi.fn() },
  $api: { useQuery: vi.fn(), useMutation: vi.fn() },
  createDevClient: vi.fn(),
}));

import { oauthApi } from './oauth-client.ts';

const HTTP_INTERNAL_SERVER_ERROR = 500;

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('oauthApi.getProviders', () => {
  test('fetches providers from the correct endpoint', async () => {
    const expected = { providers: [{ id: 'github', enabled: true }] };
    mockGet.mockResolvedValue({ data: expected, error: undefined });

    const result = await oauthApi.getProviders();

    expect(mockGet).toHaveBeenCalledWith('/api/v1/auth/oauth/providers');
    expect(result).toEqual(expected);
  });

  test('throws on error response', async () => {
    mockGet.mockResolvedValue({
      data: undefined,
      error: new Error(`OAuth API error: ${HTTP_INTERNAL_SERVER_ERROR}`),
    });

    await expect(oauthApi.getProviders()).rejects.toThrow(
      `OAuth API error: ${HTTP_INTERNAL_SERVER_ERROR}`,
    );
  });
});

describe('oauthApi.getAuthorizeUrl', () => {
  test('returns the authorize URL for github', () => {
    const url = oauthApi.getAuthorizeUrl('github' as OAuthProvider);
    expect(url).toBe('/api/v1/auth/oauth/github/authorize');
  });

  test('returns the authorize URL for google', () => {
    const url = oauthApi.getAuthorizeUrl('google' as OAuthProvider);
    expect(url).toBe('/api/v1/auth/oauth/google/authorize');
  });
});

describe('oauthApi.getAuthorizeUrl return paths', () => {
  test('encodes a deep local return path exactly once', () => {
    expect(oauthApi.getAuthorizeUrl('google' as OAuthProvider, '/jobs?remote=true#results')).toBe(
      '/api/v1/auth/oauth/google/authorize?returnUrl=%2Fjobs%3Fremote%3Dtrue%23results',
    );
  });

  test('builds account-link authorization with the account return path', () => {
    expect(oauthApi.getAuthorizeUrl('github' as OAuthProvider, '/account')).toBe(
      '/api/v1/auth/oauth/github/authorize?returnUrl=%2Faccount',
    );
  });

  test.each([
    'https://attacker.example/steal',
    '//attacker.example/steal',
    '/\\attacker.example/steal',
    '/jobs\nadmin',
    `/${'a'.repeat(2048)}`,
  ])('omits invalid return path %s', (returnUrl) => {
    expect(oauthApi.getAuthorizeUrl('google' as OAuthProvider, returnUrl)).toBe(
      '/api/v1/auth/oauth/google/authorize',
    );
  });
});

describe('oauthApi.getIdentities', () => {
  test('fetches identities from the correct endpoint', async () => {
    const expected = { identities: [] };
    mockGet.mockResolvedValue({ data: expected, error: undefined });

    const result = await oauthApi.getIdentities();

    expect(mockGet).toHaveBeenCalledWith('/api/v1/account/oauth-identities');
    expect(result).toEqual(expected);
  });
});

describe('oauthApi.unlinkProvider', () => {
  test('sends DELETE to the correct endpoint', async () => {
    mockDelete.mockResolvedValue({ data: undefined, error: undefined });

    await oauthApi.unlinkProvider('github' as OAuthProvider);

    expect(mockDelete).toHaveBeenCalledWith('/api/v1/account/oauth/{provider}', {
      params: { path: { provider: 'github' } },
    });
  });
});
