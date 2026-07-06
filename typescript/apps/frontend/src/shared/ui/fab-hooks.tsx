import { useEffect, useRef } from 'react';

const SCROLL_CLOSE_THRESHOLD: number = 5;
/** Small delay before attaching click-outside listener to avoid immediate close (ms) */
const CLICK_OUTSIDE_ATTACH_DELAY_MS: number = 10;

function useScrollClose(open: boolean, closeOnScroll: boolean, onClose: () => void): void {
  const lastScrollY = useRef(0);

  useEffect((): (() => void) | undefined => {
    if (!(closeOnScroll && open)) {
      return;
    }

    const handleScroll = (): void => {
      const currentScrollY = window.scrollY;
      const scrollDelta = Math.abs(currentScrollY - lastScrollY.current);

      if (scrollDelta > SCROLL_CLOSE_THRESHOLD) {
        onClose();
      }
      lastScrollY.current = currentScrollY;
    };

    lastScrollY.current = window.scrollY;
    window.addEventListener('scroll', handleScroll, { passive: true });
    return (): void => window.removeEventListener('scroll', handleScroll);
  }, [closeOnScroll, open, onClose]);
}

function useClickOutside(
  open: boolean,
  containerRef: React.RefObject<HTMLDivElement | null>,
  onClose: () => void,
): void {
  useEffect((): (() => void) | undefined => {
    if (!open) {
      return;
    }

    const handleClickOutside = (e: MouseEvent): void => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    const timer = setTimeout((): void => {
      document.addEventListener('click', handleClickOutside);
    }, CLICK_OUTSIDE_ATTACH_DELAY_MS);

    return (): void => {
      clearTimeout(timer);
      document.removeEventListener('click', handleClickOutside);
    };
  }, [open, onClose, containerRef]);
}

function useEscapeClose(open: boolean, onClose: () => void): void {
  useEffect((): (() => void) => {
    const handleKeyDown = (e: KeyboardEvent): void => {
      if (e.key === 'Escape' && open) {
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return (): void => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);
}

export { useClickOutside, useEscapeClose, useScrollClose };
