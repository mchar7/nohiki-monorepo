import { useEffect, useState } from 'react';
import { config } from '@/shared/config/index.ts';

/**
 * Returns a debounced version of `value` that updates after `delay` ms of inactivity.
 *
 * Defaults to `config.ui.debounceDelay` (300ms). Cleans up the pending
 * timeout on unmount or when `value`/`delay` changes.
 */
export function useDebouncedValue<T>(value: T, delay: number = config.ui.debounceDelay): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}
