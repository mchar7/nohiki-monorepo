// vitest-axe augments the legacy global `Vi.Assertion`, which
// vitest 4 no longer reads for matcher resolution (it uses `Matchers`). Re-apply
// the package's own matcher type there. Upstream: chaance/vitest-axe#12.
import type { AxeMatchers } from 'vitest-axe';
import 'vitest';

declare module 'vitest' {
  // biome-ignore lint/suspicious/noExplicitAny: must mirror vitest's Matchers<T = any> for declaration merging
  interface Matchers<T = any> extends AxeMatchers {}
}
