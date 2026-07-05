/**
 * Core schema entity types for local-first architecture.
 * Schemas define the data structure for templates.
 */

import type { LocalEntity } from './local-entity.types.ts';

export interface SchemaMetadata {
  /** Human-readable schema name */
  name: string;
  /** Optional description */
  description?: string | undefined;
  /** Schema category for organization */
  category?: string | undefined;
  /** Tags for filtering */
  tags?: string[] | undefined;
}

export interface LocalSchema extends LocalEntity {
  /** Schema metadata */
  metadata: SchemaMetadata;
  /** JSON Schema definition */
  jsonSchema: JSONSchemaDefinition;
  /** Version number for local versioning */
  version: number;
}

/**
 * JSON Schema definition with UI extension properties.
 * Supports standard JSON Schema draft-07 with x-* extensions for UI hints.
 */
export interface JSONSchemaDefinition {
  $schema?: string;
  $id?: string;
  title?: string;
  description?: string;
  type: JSONSchemaType | JSONSchemaType[];
  properties?: Record<string, JSONSchemaProperty>;
  required?: string[];
  additionalProperties?: boolean | JSONSchemaProperty;
  items?: JSONSchemaProperty | JSONSchemaProperty[];
  prefixItems?: JSONSchemaProperty[];
  minItems?: number;
  maxItems?: number;
  enum?: unknown[];
  const?: unknown;
  default?: unknown;
  examples?: unknown[];
  definitions?: Record<string, JSONSchemaProperty>;
  $defs?: Record<string, JSONSchemaProperty>;
}

export type JSONSchemaType =
  | 'string'
  | 'number'
  | 'integer'
  | 'boolean'
  | 'array'
  | 'object'
  | 'null';

export const JSON_SCHEMA_TYPES: readonly JSONSchemaType[] = [
  'string',
  'number',
  'integer',
  'boolean',
  'array',
  'object',
  'null',
];

export interface JSONSchemaProperty {
  type?: JSONSchemaType | JSONSchemaType[];
  title?: string;
  description?: string;
  format?: string;
  default?: unknown;
  examples?: unknown[];
  enum?: unknown[];
  const?: unknown;

  // String constraints
  minLength?: number;
  maxLength?: number;
  pattern?: string;

  // Number constraints
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  multipleOf?: number;

  // Array constraints
  items?: JSONSchemaProperty | JSONSchemaProperty[];
  prefixItems?: JSONSchemaProperty[];
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;

  // Object constraints
  properties?: Record<string, JSONSchemaProperty>;
  required?: string[];
  additionalProperties?: boolean | JSONSchemaProperty;
  minProperties?: number;
  maxProperties?: number;

  // Composition
  allOf?: JSONSchemaProperty[];
  anyOf?: JSONSchemaProperty[];
  oneOf?: JSONSchemaProperty[];
  not?: JSONSchemaProperty;
  if?: JSONSchemaProperty;
  then?: JSONSchemaProperty;
  else?: JSONSchemaProperty;

  // References
  $ref?: string;

  // UI Extensions (x-* properties)
  'x-widget'?:
    | 'text'
    | 'textarea'
    | 'richtext'
    | 'select'
    | 'radio'
    | 'checkbox'
    | 'date'
    | 'datetime'
    | 'color'
    | 'file';
  'x-columns'?: number;
  'x-placeholder'?: string;
  'x-show-item-labels'?: boolean;
  'x-render-as-fields'?: boolean;
  'x-field-names'?: string[];
  'x-direction'?: 'row' | 'column';
  'x-hidden'?: boolean;
  'x-order'?: number;
}

export interface CreateSchemaInput {
  metadata: SchemaMetadata;
  jsonSchema: JSONSchemaDefinition;
}

export interface UpdateSchemaInput {
  metadata?: Partial<SchemaMetadata> | undefined;
  jsonSchema?: JSONSchemaDefinition | undefined;
}
