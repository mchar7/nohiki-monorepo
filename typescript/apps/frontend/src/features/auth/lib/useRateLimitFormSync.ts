import { useEffect, useRef } from 'react';
import type { FieldValues, UseFormReturn } from 'react-hook-form';
import { useRateLimitState } from './useRateLimitState.ts';

interface RateLimitFormSync {
  readonly isRateLimited: boolean;
  readonly triggerRateLimit: (seconds: number) => void;
}

/** Sync rate-limit countdown with a form's root error, auto-clearing on expiry. */
function useRateLimitFormSync<T extends FieldValues>(
  form: UseFormReturn<T>,
  formatMessage: (seconds: number) => string,
): RateLimitFormSync {
  const { isRateLimited, secondsRemaining, triggerRateLimit } = useRateLimitState();
  const wasRateLimited = useRef(false);
  const formatRef = useRef(formatMessage);
  formatRef.current = formatMessage;

  useEffect(() => {
    if (isRateLimited) {
      wasRateLimited.current = true;
      form.setError('root', { message: formatRef.current(secondsRemaining) });
    } else if (wasRateLimited.current) {
      wasRateLimited.current = false;
      form.clearErrors('root');
    }
  }, [isRateLimited, secondsRemaining, form]);

  return { isRateLimited, triggerRateLimit };
}

export { useRateLimitFormSync };
