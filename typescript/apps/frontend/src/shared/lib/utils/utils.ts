import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Internal worker for sanitizeData. Walks the input recursively, pruning null/
 * undefined values (and optionally empty strings) from arrays and plain
 * objects. Returns `unknown` because TypeScript's structural type system
 * cannot prove that a recursive generic preserves shape across array/object
 * traversal; the single cast happens at the public boundary.
 */
function sanitizeUnknown(input: unknown, removeEmptyStrings: boolean): unknown {
  if (input === null || input === undefined) {
    return undefined;
  }

  if (Array.isArray(input)) {
    return input
      .map((item) => sanitizeUnknown(item, removeEmptyStrings))
      .filter((item) => {
        if (item === undefined || item === null) {
          return false;
        }
        if (removeEmptyStrings && item === '') {
          return false;
        }
        return true;
      });
  }

  if (typeof input === 'object') {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(input as Record<string, unknown>)) {
      const cleaned = sanitizeUnknown(value, removeEmptyStrings);
      if (
        cleaned !== undefined &&
        cleaned !== null &&
        (removeEmptyStrings ? cleaned !== '' : true)
      ) {
        result[key] = cleaned;
      }
    }
    return result;
  }

  return input;
}

/**
 * Remove null and undefined values from a data structure to prevent confusing
 * validation errors. Empty strings are preserved by default because they represent
 * valid user input that should be validated normally.
 *
 * Null/undefined inputs collapse to undefined; the runtime shape is otherwise
 * preserved (arrays stay arrays, objects stay objects). The recursive shape
 * preservation is correct at runtime but TS cannot track it through an
 * unconstrained generic, so we apply one `as T` cast at the boundary.
 */
export function sanitizeData<T = unknown>(input: T, removeEmptyStrings: boolean = false): T {
  return sanitizeUnknown(input, removeEmptyStrings) as T;
}
