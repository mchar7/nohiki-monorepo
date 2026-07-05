import { useEffect, useRef } from 'react';
import { config } from '@/shared/config/index.ts';
import { shallowEqual } from '@/shared/lib/utils/shallow-equal.ts';

interface UseFormAutoSaveOptions<T> {
  readonly data: T;
  readonly isDirty: boolean;
  readonly onSave: (data: T) => void;
  readonly debounceMs?: number;
  readonly enabled?: boolean;
  /** Custom equality comparator for deduplication.
   *  Called only after the first save (when a previous snapshot exists).
   *  Defaults to shallow object equality.
   *  Return `true` to skip saving (data unchanged), `false` to save. */
  readonly isEqual?: (a: T, b: T) => boolean;
}

/** Clears any pending timeout and sets the ref to null. */
function clearPendingTimeout(
  timeoutRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>,
): void {
  if (timeoutRef.current) {
    clearTimeout(timeoutRef.current);
    timeoutRef.current = null;
  }
}

/** Executes save if data has changed since the last saved snapshot. */
function executeSaveIfChanged<T>(
  data: T,
  onSaveRef: React.MutableRefObject<(value: T) => void>,
  isEqualRef: React.MutableRefObject<(a: T, b: T) => boolean>,
  lastSavedDataRef: React.MutableRefObject<T | undefined>,
): void {
  const lastSaved = lastSavedDataRef.current;
  const shouldSkip = lastSaved !== undefined && isEqualRef.current(data, lastSaved);
  if (!shouldSkip) {
    onSaveRef.current(data);
    lastSavedDataRef.current = data;
  }
}
export function useFormAutoSave<T>({
  data,
  isDirty,
  onSave,
  debounceMs = config.form.autoSaveDelay,
  enabled = true,
  isEqual = shallowEqual,
}: UseFormAutoSaveOptions<T>): { readonly saveNow: () => void } {
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedDataRef = useRef<T | undefined>(undefined);
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const isEqualRef = useRef(isEqual);
  isEqualRef.current = isEqual;
  const dataRef = useRef(data);
  dataRef.current = data;

  useEffect(() => {
    if (!(enabled && isDirty)) {
      return;
    }
    clearPendingTimeout(timeoutRef);
    timeoutRef.current = setTimeout((): void => {
      executeSaveIfChanged(data, onSaveRef, isEqualRef, lastSavedDataRef);
    }, debounceMs);
    return () => clearPendingTimeout(timeoutRef);
  }, [data, isDirty, debounceMs, enabled]);

  const saveNow = (): void => {
    clearPendingTimeout(timeoutRef);
    onSaveRef.current(dataRef.current);
    lastSavedDataRef.current = dataRef.current;
  };

  return { saveNow };
}
