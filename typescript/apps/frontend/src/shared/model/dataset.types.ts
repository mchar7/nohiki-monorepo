/**
 * Core dataset entity types for local-first architecture.
 * Datasets contain the actual document data populated into templates.
 */

import type { LocalEntity } from './local-entity.types.ts';

export interface DatasetMetadata {
  /** Human-readable dataset name */
  name: string;
  /** Optional description */
  description?: string | undefined;
  /** Tags for filtering */
  tags?: string[] | undefined;
}

export interface LocalDataset extends LocalEntity {
  /** Dataset metadata */
  metadata: DatasetMetadata;
  /** Associated template ID */
  templateId: string;
  /** Associated schema ID (derived from template) */
  schemaId: string | null;
  /** The actual data conforming to the schema */
  data: Record<string, unknown>;
  /** Cached rendered HTML (for performance) */
  cachedHtml?: string | undefined;
  /** When the HTML was cached */
  htmlCachedAt?: string | undefined;
}

export interface CreateDatasetInput {
  metadata: DatasetMetadata;
  templateId: string;
  data?: Record<string, unknown>;
}

export interface UpdateDatasetInput {
  metadata?: Partial<DatasetMetadata> | undefined;
  data?: Record<string, unknown> | undefined;
}
