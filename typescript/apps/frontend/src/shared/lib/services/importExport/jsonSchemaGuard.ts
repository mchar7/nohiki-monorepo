/**
 * Runtime guards for converting between the strongly-typed `JSONSchemaDefinition`
 * (used internally for editor + form rendering) and the loose
 * `Record<string, unknown>` shape produced by deserializing imported JSON.
 *
 * Without these guards, deserialization boundaries would need
 * `as unknown as JSONSchemaDefinition` casts, which silently accept malformed
 * input. The guards make the contract explicit: invalid shapes are detected at
 * the boundary and either coerced to a safe fallback or rejected.
 */

import type { JSONSchemaDefinition, JSONSchemaType } from '@/shared/model/schema.types.ts';
import { JSON_SCHEMA_TYPES } from '@/shared/model/schema.types.ts';

// O(1) membership test over the canonical runtime values exported beside the
// JSONSchemaType union. Building this once at module load makes each validation
// call independent of the union size.
const VALID_JSON_SCHEMA_TYPES: ReadonlySet<JSONSchemaType> = new Set(JSON_SCHEMA_TYPES);

function isJSONSchemaType(value: unknown): value is JSONSchemaType {
  return typeof value === 'string' && VALID_JSON_SCHEMA_TYPES.has(value as JSONSchemaType);
}

function isValidTypeField(value: unknown): boolean {
  if (isJSONSchemaType(value)) {
    return true;
  }
  return Array.isArray(value) && value.every(isJSONSchemaType);
}

/**
 * Runtime check that an arbitrary object satisfies the required shape of
 * `JSONSchemaDefinition`.
 *
 * The only structurally-required field is `type` (a JSONSchemaType or an array
 * of them). All other JSON Schema fields are optional.
 */
function isJSONSchemaDefinition(value: unknown): value is JSONSchemaDefinition {
  if (value === null || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return isValidTypeField(candidate.type);
}

/**
 * Coerces an arbitrary object to a `JSONSchemaDefinition`, returning null when
 * the input does not satisfy the minimum shape. Use this at deserialization
 * boundaries where invalid input is expected and must be rejected gracefully.
 */
function asJSONSchemaDefinition(value: unknown): JSONSchemaDefinition | null {
  return isJSONSchemaDefinition(value) ? value : null;
}

export { asJSONSchemaDefinition };
