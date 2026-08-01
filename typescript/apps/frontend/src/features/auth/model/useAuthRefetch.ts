import { useSession } from '@/shared/api/index.ts';

function useAuthRefetch(): ReturnType<typeof useSession>['refetch'] {
  const { refetch } = useSession();
  return refetch;
}

export { useAuthRefetch };
