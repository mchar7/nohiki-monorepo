import { useEffect, useRef, useState } from 'react';

const MS_PER_SECOND = 1000;

interface RateLimitState {
  readonly isRateLimited: boolean;
  readonly secondsRemaining: number;
  readonly triggerRateLimit: (seconds: number) => void;
}

/** Manages a countdown timer for rate-limit cooldown periods. */
function useRateLimitState(): RateLimitState {
  const [secondsRemaining, setSecondsRemaining] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearCountdown = (): void => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  const triggerRateLimit = (seconds: number): void => {
    clearCountdown();
    setSecondsRemaining(seconds);

    intervalRef.current = setInterval(() => {
      setSecondsRemaining((prev) => {
        if (prev <= 1) {
          clearCountdown();
          return 0;
        }
        return prev - 1;
      });
    }, MS_PER_SECOND);
  };

  // Clean up interval on unmount
  useEffect(
    () => (): void => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    },
    [],
  );

  return {
    isRateLimited: secondsRemaining > 0,
    secondsRemaining,
    triggerRateLimit,
  };
}

export { useRateLimitState };
