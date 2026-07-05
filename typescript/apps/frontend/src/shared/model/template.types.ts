/**
 * Core template entity types for local-first architecture.
 * Templates are stored locally with optional backend sync.
 */

import type { LocalEntity } from './local-entity.types.ts';

export interface TemplateMetadata {
  /** Template identifier (present for API-backed templates) */
  id?: string | undefined;
  /** Human-readable template name */
  name: string;
  /** Optional description */
  description?: string | undefined;
  /** Template version string */
  version?: string | undefined;
  /** Template engine identifier */
  engine?: string | undefined;
  /** Template category for organization */
  category?: string | undefined;
  /** Tags for filtering */
  tags?: string[] | undefined;
  /** Page size configuration */
  pageSize?: PageSizeConfig | undefined;
  /** JavaScript requirement metadata */
  requiresJavaScript?: JavaScriptRequirement | undefined;
}

export interface JavaScriptRequirement {
  /** Whether JavaScript execution is required */
  required: boolean;
  /** Reason for requiring JavaScript */
  reason?: string | undefined;
}

export interface PageSizeConfig {
  width: number;
  height: number;
  unit: 'mm' | 'in' | 'px';
  orientation: 'portrait' | 'landscape';
}

export const DEFAULT_PAGE_SIZE: PageSizeConfig = {
  width: 210,
  height: 297,
  unit: 'mm',
  orientation: 'portrait',
};

export interface LocalTemplate extends LocalEntity {
  /** Template metadata */
  metadata: TemplateMetadata;
  /** Jinja2/HTML template content */
  content: string;
  /** Associated schema ID for data validation */
  schemaId: string | null;
  /** Version number for local versioning */
  version: number;
}

export interface CreateTemplateInput {
  metadata: TemplateMetadata;
  content: string;
  schemaId?: string | null | undefined;
}

export interface UpdateTemplateInput {
  metadata?: Partial<TemplateMetadata> | undefined;
  content?: string | undefined;
  schemaId?: string | null | undefined;
}
