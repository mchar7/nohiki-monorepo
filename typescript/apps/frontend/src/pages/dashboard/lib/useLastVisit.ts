import { useEffect, useRef, useState } from 'react';

const STORAGE_KEY = 'nohiki_dashboard_last_visit';

export interface UseLastVisitReturn {
  lastVisit: Date | null;
  newSinceLastVisit: (items: readonly { created_at: string }[]) => number;
}

/**
 * Tracks the user's last dashboard visit via localStorage.
 *
 * On mount, reads the previous visit timestamp and writes the current time.
 * A ref guard prevents double-writes in React Strict Mode (dev only).
 *
 * Returns the previous visit date and a helper to count items created since then.
 */
export function useLastVisit(): UseLastVisitReturn {
  const [lastVisit, setLastVisit] = useState<Date | null>(null);
  const hasWritten = useRef(false);

  useEffect(() => {
    if (hasWritten.current) {
      return;
    }
    hasWritten.current = true;

    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = new Date(stored);
        // Guard against invalid stored dates (NaN from corrupted values)
        if (!Number.isNaN(parsed.getTime())) {
          setLastVisit(parsed);
        }
      }
    } catch {
      // localStorage may throw in private browsing or when quota exceeded
    }

    try {
      localStorage.setItem(STORAGE_KEY, new Date().toISOString());
    } catch {
      // Silently ignore write failures
    }
  }, []);

  function newSinceLastVisit(items: readonly { created_at: string }[]): number {
    if (!lastVisit) {
      return 0;
    }

    const threshold = lastVisit.getTime();
    let count = 0;
    for (const item of items) {
      if (new Date(item.created_at).getTime() > threshold) {
        count += 1;
      }
    }
    return count;
  }

  return { lastVisit, newSinceLastVisit };
}
