import { $api, CACHE_CONFIG } from '@/shared/api/index.ts';

export function useAccount() {
  return $api.useQuery('get', '/api/v1/account', undefined, { ...CACHE_CONFIG.DYNAMIC });
}
