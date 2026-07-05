/**
 * Common types shared across all entities.
 */

/** Sync status for local-first entities that may sync with backend */
export type SyncStatus = 'local-only' | 'synced' | 'pending-sync' | 'conflict';

/** Base interface for all local-first entities */
export interface LocalEntity {
  /** Unique local identifier (nanoid) */
  id: string;
  /** ISO timestamp of creation */
  createdAt: string;
  /** ISO timestamp of last update */
  updatedAt: string;
  /** Optional remote ID if synced with backend */
  remoteId?: string;
  /** Sync status */
  syncStatus: SyncStatus;
  /** Last sync timestamp */
  lastSyncedAt?: string;
}
