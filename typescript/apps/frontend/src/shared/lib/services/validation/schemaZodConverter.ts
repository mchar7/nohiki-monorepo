/**
 * JSON Schema to Zod schema conversion utilities.
 * Converts a subset of JSON Schema features to Zod schemas for runtime validation.
 */

import { z } from 'zod';
import type { JSONSchemaDefinition, JSONSchemaProperty } from '@/shared/model/schema.types.ts';

function buildStringSchema(prop: JSONSchemaProperty): z.ZodString {
  let schema = z.string();

  if (prop.minLength !== undefined) {
    schema = schema.min(prop.minLength);
  }
  if (prop.maxLength !== undefined) {
    schema = schema.max(prop.maxLength);
  }
  if (prop.pattern) {
    // biome-ignore lint/nursery/useUnicodeRegex: Dynamic JSON Schema patterns must preserve their source flags and legacy semantics.
    schema = schema.regex(new RegExp(prop.pattern));
  }

  return schema;
}

function buildNumberSchema(prop: JSONSchemaProperty, isInteger: boolean): z.ZodNumber {
  let schema = z.number();

  if (isInteger) {
    schema = schema.int();
  }
  if (prop.minimum !== undefined) {
    schema = schema.min(prop.minimum);
  }
  if (prop.maximum !== undefined) {
    schema = schema.max(prop.maximum);
  }
  if (prop.exclusiveMinimum !== undefined) {
    schema = schema.gt(prop.exclusiveMinimum);
  }
  if (prop.exclusiveMaximum !== undefined) {
    schema = schema.lt(prop.exclusiveMaximum);
  }
  if (prop.multipleOf !== undefined) {
    schema = schema.multipleOf(prop.multipleOf);
  }

  return schema;
}

function buildArraySchema(prop: JSONSchemaProperty): z.ZodArray<z.ZodTypeAny> {
  let itemSchema: z.ZodTypeAny = z.unknown();

  if (prop.items && !Array.isArray(prop.items)) {
    itemSchema = convertProperty(prop.items);
  }

  let schema = z.array(itemSchema);

  if (prop.minItems !== undefined) {
    schema = schema.min(prop.minItems);
  }
  if (prop.maxItems !== undefined) {
    schema = schema.max(prop.maxItems);
  }

  return schema;
}

function buildObjectSchema(prop: JSONSchemaProperty): z.ZodTypeAny {
  const shape: Record<string, z.ZodTypeAny> = {};

  if (prop.properties) {
    for (const [key, value] of Object.entries(prop.properties)) {
      let fieldSchema = convertProperty(value);

      // Make non-required fields optional
      if (!prop.required?.includes(key)) {
        fieldSchema = fieldSchema.optional();
      }

      shape[key] = fieldSchema;
    }
  }

  return z.object(shape);
}

function convertProperty(prop: JSONSchemaProperty): z.ZodTypeAny {
  const type = Array.isArray(prop.type) ? prop.type[0] : prop.type;

  let zodSchema: z.ZodTypeAny;

  switch (type) {
    case 'string':
      zodSchema = buildStringSchema(prop);
      break;
    case 'number':
    case 'integer':
      zodSchema = buildNumberSchema(prop, type === 'integer');
      break;
    case 'boolean':
      zodSchema = z.boolean();
      break;
    case 'array':
      zodSchema = buildArraySchema(prop);
      break;
    case 'object':
      zodSchema = buildObjectSchema(prop);
      break;
    case 'null':
      zodSchema = z.null();
      break;
    default:
      zodSchema = z.unknown();
  }

  // Handle nullable types
  if (Array.isArray(prop.type) && prop.type.includes('null')) {
    zodSchema = zodSchema.nullable();
  }

  // Handle default values
  if (prop.default !== undefined) {
    zodSchema = zodSchema.default(prop.default);
  }

  return zodSchema;
}

/**
 * Converts a JSON Schema to a Zod schema for runtime validation.
 * Supports a subset of JSON Schema features.
 */
function jsonSchemaToZod(schema: JSONSchemaDefinition): z.ZodTypeAny {
  return convertProperty(schema);
}

export { jsonSchemaToZod };
