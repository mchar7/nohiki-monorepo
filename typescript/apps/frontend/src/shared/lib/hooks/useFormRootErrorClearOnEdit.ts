import { useEffect, useRef } from 'react';
import type { FieldValues, UseFormReturn } from 'react-hook-form';

/**
 * The subset of UseFormReturn this hook depends on. Narrowing the parameter
 * type lets test code construct a minimal mock object without an unsafe cast
 * to the full UseFormReturn surface (which has dozens of unused methods).
 * UseFormReturn satisfies this interface structurally, so production callers
 * are unaffected.
 */
type FormRootErrorClearOnEditTarget<T extends FieldValues> = Pick<
  UseFormReturn<T>,
  'formState' | 'watch' | 'clearErrors'
>;

/**
 * Clears the form's root error when the user edits any field after the error appeared.
 *
 * The error stays visible until the user modifies a field value, signaling intent to retry.
 *
 * @param form - A subset of the react-hook-form return value (see `FormRootErrorClearOnEditTarget`).
 */
function useFormRootErrorClearOnEdit<T extends FieldValues>(
  form: FormRootErrorClearOnEditTarget<T>,
): void {
  const errorActiveRef = useRef(false);

  // Track root error presence bidirectionally
  const rootError = form.formState.errors.root;
  useEffect(() => {
    errorActiveRef.current = rootError !== undefined;
  }, [rootError]);

  // Subscribe to field changes and clear root error when user edits after error
  useEffect(() => {
    const subscription = form.watch((_value, { name }) => {
      if (errorActiveRef.current && name !== undefined) {
        form.clearErrors('root');
        errorActiveRef.current = false;
      }
    });
    return () => {
      subscription.unsubscribe();
    };
  }, [form]);
}

export { useFormRootErrorClearOnEdit };
