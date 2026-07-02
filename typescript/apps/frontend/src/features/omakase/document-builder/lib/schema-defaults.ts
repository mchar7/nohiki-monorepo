/**
 * Shared utilities for extracting default values from JSON Schema
 */

import type { DatasetData } from '../model/index.ts';

const TYPE_DEFAULTS: Record<string, unknown> = {
  string: '',
  number: 0,
  integer: 0,
  boolean: false,
  array: [],
  object: {},
};

/**
 * Get the default value for a JSON Schema property.
 *
 * Recursively resolves defaults for nested objects. For simple types,
 * returns the type-appropriate empty value (e.g., '' for string, 0 for number).
 */
export function getPropertyDefault(property: Record<string, unknown>): unknown {
  if (property.default !== undefined) {
    return property.default;
  }

  const propType = property.type as string;

  if (propType === 'object' && property.properties) {
    return extractDefaultsFromSchema(property);
  }

  if (propType in TYPE_DEFAULTS) {
    return TYPE_DEFAULTS[propType];
  }
  return null;
}

/**
 * Extract default values from a JSON Schema object.
 *
 * Iterates over all properties and resolves their defaults using
 * `getPropertyDefault`. Non-object schemas return an empty object.
 */
export function extractDefaultsFromSchema(jsonSchema: Record<string, unknown>): DatasetData {
  if (jsonSchema.type !== 'object' || !jsonSchema.properties) {
    return {};
  }

  const properties = jsonSchema.properties as Record<string, Record<string, unknown>>;
  const defaults: DatasetData = {};

  for (const [key, property] of Object.entries(properties)) {
    defaults[key] = getPropertyDefault(property);
  }

  return defaults;
}
