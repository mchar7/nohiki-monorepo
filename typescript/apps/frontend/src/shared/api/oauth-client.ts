import { getSafeReturnUrl } from '@/shared/lib/security/sanitization.ts';
import { fetchClient } from './client.ts';
import type { OAuthIdentitiesResponse, OAuthProvider, OAuthProvidersResponse } from './types.ts';

/**
 * OAuth API facade using openapi-fetch.
 * Endpoints exist in the OpenAPI schema and are now fully type-safe.
 */
export const oauthApi = {
  getProviders: async (): Promise<OAuthProvidersResponse> => {
    const { data, error } = await fetchClient.GET('/api/v1/auth/oauth/providers');
    if (error) {
      throw error;
    }
    return data;
  },

  getAuthorizeUrl: (provider: OAuthProvider, returnUrl?: string): string => {
    const authorizeUrl = `/api/v1/auth/oauth/${provider}/authorize`;
    const safeReturnUrl = getSafeReturnUrl(returnUrl, '');
    if (!safeReturnUrl) {
      return authorizeUrl;
    }

    const query = new URLSearchParams({ returnUrl: safeReturnUrl });
    return `${authorizeUrl}?${query.toString()}`;
  },

  getIdentities: async (): Promise<OAuthIdentitiesResponse> => {
    const { data, error } = await fetchClient.GET('/api/v1/account/oauth-identities');
    if (error) {
      throw error;
    }
    return data;
  },

  unlinkProvider: async (provider: OAuthProvider): Promise<void> => {
    const { error } = await fetchClient.DELETE('/api/v1/account/oauth/{provider}', {
      params: { path: { provider } },
    });
    if (error) {
      throw error;
    }
  },
} as const;
