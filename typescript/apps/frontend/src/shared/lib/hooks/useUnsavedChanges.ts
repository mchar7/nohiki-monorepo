import { useBlocker } from '@tanstack/react-router';

/**
 * Blocks both in-app and browser-level navigation when the form has unsaved changes.
 *
 * Uses TanStack Router's `useBlocker` with `withResolver: true` to intercept
 * in-app navigation (link clicks, programmatic navigate) and return the blocker
 * state so the caller can render `UnsavedChangesDialog`.
 *
 * Also enables the browser's native `beforeunload` prompt when dirty, covering
 * tab close, external URL navigation, and browser back/forward.
 *
 * Usage:
 * ```tsx
 * const blocker = useUnsavedChanges(form.formState.isDirty);
 * return (
 *   <>
 *     <YourForm />
 *     <UnsavedChangesDialog
 *       open={blocker.status === 'blocked'}
 *       onConfirm={blocker.proceed ?? (() => {})}
 *       onCancel={blocker.reset ?? (() => {})}
 *     />
 *   </>
 * );
 * ```
 *
 * @param isDirty - Whether the form has unsaved changes.
 * @returns Blocker state with status, proceed, and reset for dialog control.
 */
export function useUnsavedChanges(isDirty: boolean): {
  status: 'idle' | 'blocked';
  proceed: (() => void) | undefined;
  reset: (() => void) | undefined;
} {
  return useBlocker({
    shouldBlockFn: () => isDirty,
    enableBeforeUnload: isDirty,
    withResolver: true,
  });
}
