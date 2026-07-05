import { useMutationState } from '@tanstack/react-query';

/**
 * Entity types that can be tracked for pending mutations.
 * Derived from the domain model: profiles, attachments, documents, correlations, account.
 */
type EntityType = 'profile' | 'attachment' | 'document' | 'correlation' | 'account';

/** Map of mutation key prefixes to entity types for grouping */
const ENTITY_KEY_MAP: ReadonlyMap<string, EntityType> = new Map([
  ['profiles', 'profile'],
  ['attachments', 'attachment'],
  ['documents', 'document'],
  ['correlations', 'correlation'],
  ['account', 'account'],
]);

interface UsePendingMutationsResult {
  /** Check whether a specific mutation key has in-flight mutations */
  isPending: (key: string) => boolean;
  /** All currently in-flight mutation keys */
  pendingKeys: ReadonlySet<string>;
  /** All entity types with in-flight mutations */
  pendingEntities: ReadonlySet<EntityType>;
  /** Check whether a specific entity type has in-flight mutations */
  isEntityPending: (entity: EntityType) => boolean;
  /** Total number of in-flight mutations */
  pendingCount: number;
}

/**
 * Tracks in-flight mutations across the application using TanStack Query's
 * mutation state. Groups mutations by entity type for UI feedback.
 *
 * Relies on `useMutationState` to observe all active mutations without
 * coupling to individual mutation hooks.
 */
export function usePendingMutations(): UsePendingMutationsResult {
  const pendingMutations = useMutationState({
    filters: { status: 'pending' },
    select: (mutation: { options: { mutationKey?: readonly unknown[] } }) =>
      mutation.options.mutationKey,
  });

  const pendingKeySet = new Set<string>();
  const pendingEntitySet = new Set<EntityType>();

  for (const key of pendingMutations) {
    if (Array.isArray(key) && key.length > 0) {
      const keyStr = String(key[0]);
      pendingKeySet.add(keyStr);

      const entity = ENTITY_KEY_MAP.get(keyStr);
      if (entity) {
        pendingEntitySet.add(entity);
      }
    }
  }

  const isPending = (key: string): boolean => pendingKeySet.has(key);

  const isEntityPending = (entity: EntityType): boolean => pendingEntitySet.has(entity);

  return {
    isPending,
    pendingKeys: pendingKeySet,
    pendingEntities: pendingEntitySet,
    isEntityPending,
    pendingCount: pendingMutations.length,
  };
}
