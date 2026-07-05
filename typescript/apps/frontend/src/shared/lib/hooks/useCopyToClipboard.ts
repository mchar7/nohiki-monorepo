import { useEffect, useRef, useState } from 'react';

const COPIED_RESET_MS: number = 2000;

/**
 * Hook for copying text to the clipboard with a temporary "copied" indicator.
 *
 * Uses `navigator.clipboard.writeText()` and automatically resets the
 * `isCopied` flag after 2 seconds.
 *
 * @returns Tuple of `[copy, isCopied]` where `copy` triggers the clipboard
 *   write and `isCopied` is `true` for 2s after a successful copy.
 *
 * @example
 * ```tsx
 * const [copy, isCopied] = useCopyToClipboard();
 *
 * <Button onClick={() => copy(someText)}>
 *   {isCopied ? 'Copied!' : 'Copy'}
 * </Button>
 * ```
 */
export function useCopyToClipboard(): [(text: string) => Promise<void>, boolean] {
  const [isCopied, setIsCopied] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const copy = async (text: string): Promise<void> => {
    await navigator.clipboard.writeText(text);
    setIsCopied(true);

    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(() => {
      setIsCopied(false);
      timeoutRef.current = null;
    }, COPIED_RESET_MS);
  };

  useEffect(
    (): (() => void) => (): void => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    },
    [],
  );

  return [copy, isCopied];
}
