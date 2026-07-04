/**
 * TanStack Query hook for fetching decorative job listings from the Cloudflare Edge Worker.
 *
 * Designed for graceful degradation: all failures return an empty response so
 * the auth page always renders without loading or error states.
 */
import { useQuery } from '@tanstack/react-query';
import { CACHE_CONFIG } from '@/shared/api';
import { config } from '@/shared/config';
import type { AuthListingsResponse } from '../model';

const EMPTY_RESPONSE: AuthListingsResponse = { listings: [], country: '' };

export function useAuthListings() {
  const { workerUrl } = config.services.authListings;

  return useQuery({
    queryKey: ['auth-listings'] as const,
    queryFn: async (): Promise<AuthListingsResponse> => {
      if (!workerUrl) {
        return EMPTY_RESPONSE;
      }

      try {
        const response = await fetch(`${workerUrl}/auth-listings`);
        if (!response.ok) {
          return EMPTY_RESPONSE;
        }
        return (await response.json()) as AuthListingsResponse;
      } catch {
        return EMPTY_RESPONSE;
      }
    },
    enabled: Boolean(workerUrl),
    staleTime: CACHE_CONFIG.AUTH_LISTINGS.staleTime,
    gcTime: CACHE_CONFIG.AUTH_LISTINGS.gcTime,
    retry: false,
    placeholderData: EMPTY_RESPONSE,
  });
}
