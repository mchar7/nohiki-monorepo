// `!` is banned repo-wide and `?.` inside an assertion silently weakens it.
export function nonNull<T>(value: T, message?: string): NonNullable<T> {
  if (value === null || value === undefined) {
    throw new Error(message ?? 'Expected value to be non-null');
  }
  return value;
}
