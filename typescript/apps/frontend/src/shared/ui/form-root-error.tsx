import { AlertCircle } from 'lucide-react';
import type { JSX } from 'react';
import type { FormRootErrorProps } from './form-root-error.types.ts';

/** Alert banner for form-level root errors. Renders when `error` is truthy. */
function FormRootError({ error }: FormRootErrorProps): JSX.Element | null {
  if (!error) {
    return null;
  }

  return (
    <div
      role="alert"
      data-testid="form-root-error"
      className="fade-in flex animate-in items-center gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-3 text-destructive text-sm"
    >
      <AlertCircle className="size-4 shrink-0" aria-hidden="true" />
      <span>{error}</span>
    </div>
  );
}

export { FormRootError };
