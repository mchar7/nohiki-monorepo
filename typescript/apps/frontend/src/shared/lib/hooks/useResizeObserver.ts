import { type RefObject, useEffect, useRef, useState } from 'react';
import { logger } from '@/shared/lib/utils/logger.ts';

interface Size {
  width: number;
  height: number;
}

/**
 * Hook to observe element size changes using ResizeObserver
 * Returns the current dimensions of the observed element
 * Debounced with requestAnimationFrame for performance
 */
export function useResizeObserver<T extends HTMLElement = HTMLDivElement>(): [
  React.RefObject<T>,
  Size,
] {
  const elementRef = useRef<T>(null);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  const rafIdRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) {
      return;
    }

    // Check if ResizeObserver is available
    if (typeof ResizeObserver === 'undefined') {
      logger.warn('ResizeObserver not available, falling back to static size');
      // Fallback to initial size measurement
      const rect = element.getBoundingClientRect();
      setSize({ width: Math.floor(rect.width), height: Math.floor(rect.height) });
      return;
    }

    const handleResize = (entries: ResizeObserverEntry[]): void => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
      }

      rafIdRef.current = requestAnimationFrame(() => {
        const [entry] = entries;
        if (entry) {
          const { width, height } = entry.contentRect;
          setSize({ width: Math.floor(width), height: Math.floor(height) });
        }
      });
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(element);

    // Initial size measurement
    const rect = element.getBoundingClientRect();
    setSize({ width: Math.floor(rect.width), height: Math.floor(rect.height) });

    return () => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
      }
      resizeObserver.disconnect();
    };
  }, []);

  return [elementRef as RefObject<T>, size];
}
