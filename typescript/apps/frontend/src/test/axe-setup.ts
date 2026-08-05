import type { ExpectStatic } from 'vitest';
import { expect } from 'vitest';

type MatchersArg = Parameters<ExpectStatic['extend']>[0];

// vitest-axe packaging bug: chunked .d.ts re-exports are incompatible
// with verbatimModuleSyntax (toHaveNoViolations misclassified as type-only).
// Import the runtime JS directly to bypass the broken type declaration.
const matchers: MatchersArg = (await import(
  /* @vite-ignore */ 'vitest-axe/dist/matchers.js'
)) as MatchersArg;

expect.extend(matchers);
