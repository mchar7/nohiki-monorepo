import { z } from 'zod';

interface ListSearchResult<TSort extends string> {
  page: number;
  sort: TSort;
  dir: 'asc' | 'desc';
}

/**
 * Builds a Zod search schema for list-page URL params: `?page=1&sort=name&dir=asc`.
 *
 * Use as the `validateSearch` option in TanStack Router route definitions.
 * Invalid or missing params fall back to defaults - no runtime errors.
 *
 * @param sortFields - Tuple of valid sort field names (first is default unless overridden).
 * @param defaults - Optional overrides for default sort field and direction.
 * @returns Zod object schema compatible with TanStack Router's `validateSearch`.
 *
 * Examples:
 *   listSearchSchema(['name', 'keywords'])
 *   listSearchSchema(['posted_at', 'company'], { sort: 'posted_at', dir: 'desc' })
 */
export function listSearchSchema<T extends [string, ...string[]]>(
  sortFields: T,
  defaults?: { sort?: T[number]; dir?: 'asc' | 'desc' },
): z.ZodSchema<ListSearchResult<T[number]>> {
  const defaultSort: T[number] = defaults?.sort ?? sortFields[0];
  const defaultDir: 'asc' | 'desc' = defaults?.dir ?? 'asc';

  return z.object({
    page: z.number().int().min(1).optional().default(1),
    sort: z.enum(sortFields).catch(defaultSort),
    dir: z.enum(['asc', 'desc']).catch(defaultDir),
  }) as z.ZodSchema<ListSearchResult<T[number]>>;
}
