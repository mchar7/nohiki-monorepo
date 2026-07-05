/**
 * Performs a shallow equality check between two values.
 *
 * Uses O(k) key-by-key comparison where k is the number of keys, avoiding
 * the GC pressure and CPU cost of JSON serialisation. `Object.is` is used as
 * a fast path for reference equality and for comparing individual key values.
 *
 * Does NOT recurse into nested objects. Callers requiring deep equality should
 * use a dedicated deep-equal utility instead.
 */
function shallowEqual<T>(a: T, b: T): boolean {
  // Fast path: identical references, same primitives, NaN, null, undefined
  if (Object.is(a, b)) {
    return true;
  }

  // One or both are null or a non-object primitive; distinct values not caught above
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') {
    return false;
  }

  // Safe cast: both values have been narrowed to non-null objects
  const objA = a as Record<string, unknown>;
  const objB = b as Record<string, unknown>;
  const keysA = Object.keys(objA);

  if (keysA.length !== Object.keys(objB).length) {
    return false;
  }

  return keysA.every((key) => Object.hasOwn(objB, key) && Object.is(objA[key], objB[key]));
}

export { shallowEqual };
