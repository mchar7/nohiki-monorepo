/** Entity types trackable by usePendingMutations. */
type EntityType = 'profile' | 'attachment' | 'document' | 'correlation' | 'account';

interface PendingMutationBadgeProps {
  /** Which domain entity to check for in-flight mutations. */
  readonly entityType: EntityType;
  /** Optional className for the wrapper span. */
  readonly className?: string;
}

export type { PendingMutationBadgeProps };
