/**
 * Thin top-of-viewport progress bar shown during route transitions.
 *
 * Uses useRouterState to detect when TanStack Router is pending. Animates
 * from 0 → ~80% during the transition, then quickly completes to 100% and
 * fades out. Respects prefers-reduced-motion by skipping animation and
 * simply showing/hiding the bar instantly.
 */

import { useRouterState } from '@tanstack/react-router';
import type { JSX } from 'react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { usePrefersReducedMotion } from '@/shared/lib/index.ts';
import { cn } from '@/shared/lib/utils/utils.ts';

type ProgressPhase = 'idle' | 'running' | 'completing' | 'done';

/** Duration (ms) the bar stays at 100% width before fading out. */
const COMPLETION_HOLD_MS = 200;
/** Duration (ms) of the fade-out CSS transition. Must match the Tailwind class. */
const FADE_OUT_MS = 300;

/** aria-valuenow when the bar is at an indeterminate mid-point. */
const ARIA_VALUE_HALF = 50;
/** aria-valuenow when the bar has completed. */
const ARIA_VALUE_FULL = 100;

function useProgressPhase(isPending: boolean): ProgressPhase {
  const [phase, setPhase] = useState<ProgressPhase>('idle');
  const phaseRef = useRef<ProgressPhase>('idle');
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep phaseRef in sync so the effect closure reads the current value without
  // requiring phase as an effect dependency (avoids re-subscribing on every render).
  phaseRef.current = phase;

  useEffect(() => {
    const clearPending = (): void => {
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };

    if (isPending) {
      clearPending();
      setPhase('running');
      phaseRef.current = 'running';
      return clearPending;
    }

    // Route resolved - complete the bar then fade it out
    if (phaseRef.current === 'running') {
      setPhase('completing');
      phaseRef.current = 'completing';

      timeoutRef.current = setTimeout(() => {
        setPhase('done');
        phaseRef.current = 'done';

        timeoutRef.current = setTimeout(() => {
          setPhase('idle');
          phaseRef.current = 'idle';
        }, FADE_OUT_MS);
      }, COMPLETION_HOLD_MS);
    }

    return clearPending;
  }, [isPending]);

  return phase;
}

export function RouteProgress(): JSX.Element | null {
  const { t } = useTranslation(['common']);
  const routerState = useRouterState();
  const isPending = routerState.status === 'pending';
  const prefersReducedMotion = usePrefersReducedMotion();
  const phase = useProgressPhase(isPending);

  if (phase === 'idle') {
    return null;
  }

  if (prefersReducedMotion) {
    // No animation - show a static full-width bar while pending, hide when done
    return (
      <div
        role="progressbar"
        aria-label={t('a11y.pageLoading')}
        aria-valuemin={0}
        aria-valuemax={ARIA_VALUE_FULL}
        aria-valuenow={isPending ? ARIA_VALUE_HALF : ARIA_VALUE_FULL}
        className="fixed top-0 right-0 left-0 z-50 h-[3px] bg-primary"
      />
    );
  }

  return (
    <div
      role="progressbar"
      aria-label={t('a11y.pageLoading')}
      aria-valuemin={0}
      aria-valuemax={ARIA_VALUE_FULL}
      aria-valuenow={phase === 'completing' || phase === 'done' ? ARIA_VALUE_FULL : ARIA_VALUE_HALF}
      className={cn(
        'fixed top-0 right-0 left-0 z-50 h-[3px] origin-left bg-primary',
        // Running: animate toward ~80% with a slow ease-out
        phase === 'running' && 'animate-route-progress',
        // Completing: snap quickly to full width
        phase === 'completing' && 'w-full transition-[width] duration-150 ease-out',
        // Done: fade out
        phase === 'done' && 'w-full opacity-0 transition-opacity duration-300 ease-out',
      )}
    />
  );
}
