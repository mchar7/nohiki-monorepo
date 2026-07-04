import type { JSX } from 'react';
import { useEffect, useRef, useState } from 'react';
import { useAuthListings } from '../api/useAuthListings';
import type { AuthListingItem } from '../model/types';
import { AuthListingCard } from './AuthListingCard';
import {
  BLUR_INTENSITY,
  BLUR_SCALE_THRESHOLD,
  type CardSlot,
  clearAllTimers,
  computeSlotVisuals,
  FADE_OUT_MS,
  GRID_COLS,
  GRID_JITTER,
  GRID_MAX_XY,
  GRID_STEP_X,
  GRID_STEP_Y,
  getNextListing,
  getRandomProps,
  MAX_CARDS,
  REDUCED_CARDS,
  REDUCED_OPACITY_MIN,
  REDUCED_OPACITY_SPREAD,
  REDUCED_SCALE_BASE,
  REDUCED_SCALE_SPREAD,
  REDUCED_TILT_OFFSET,
  REDUCED_TILT_SPREAD,
  STYLES,
  scheduleCycleAfterSwap,
  shuffleArray,
  startVisibleTimers,
} from './authCanvasUtils';

function useReducedMotion(): boolean {
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = globalThis.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mediaQuery.matches);

    const handler = (e: MediaQueryListEvent): void => setReducedMotion(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  return reducedMotion;
}

function useTabVisibility(): boolean {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    const handler = (): void => {
      setIsVisible(document.visibilityState === 'visible');
    };
    document.addEventListener('visibilitychange', handler);
    handler();
    return () => document.removeEventListener('visibilitychange', handler);
  }, []);

  return isVisible;
}

interface CanvasStateReturn {
  shuffledListings: AuthListingItem[];
  slots: CardSlot[];
  setSlots: React.Dispatch<React.SetStateAction<CardSlot[]>>;
  poolRef: React.MutableRefObject<CardSlot[]>;
  listIndexRef: React.MutableRefObject<number>;
}

function useCanvasState(data: { listings: AuthListingItem[] } | undefined): CanvasStateReturn {
  const [shuffledListings, setShuffledListings] = useState<AuthListingItem[]>([]);
  const [slots, setSlots] = useState<CardSlot[]>([]);
  const poolRef = useRef<CardSlot[]>([]);
  const listIndexRef = useRef(0);

  // Shuffle listings once they arrive
  useEffect(() => {
    const listings = data?.listings ?? [];
    if (listings.length > 0 && shuffledListings.length === 0) {
      setShuffledListings(shuffleArray(listings));
    }
  }, [data?.listings, shuffledListings.length]);

  return { shuffledListings, slots, setSlots, poolRef, listIndexRef };
}

interface CanvasInitArgs {
  readonly shuffledListings: AuthListingItem[];
  readonly isReducedMotion: boolean;
  readonly poolRef: React.MutableRefObject<CardSlot[]>;
  readonly listIndexRef: React.MutableRefObject<number>;
  readonly setSlots: (slots: CardSlot[]) => void;
}

function useCanvasInitialization({
  shuffledListings,
  isReducedMotion,
  poolRef,
  listIndexRef,
  setSlots,
}: CanvasInitArgs): void {
  useEffect(() => {
    if (shuffledListings.length === 0) {
      return;
    }
    if (poolRef.current.length > 0) {
      return;
    }

    const initialSlots: CardSlot[] = [];
    const numCards = isReducedMotion
      ? Math.min(REDUCED_CARDS, shuffledListings.length)
      : Math.min(MAX_CARDS, shuffledListings.length);

    if (isReducedMotion) {
      for (let i = 0; i < numCards; i += 1) {
        const c = i % GRID_COLS;
        const r = Math.floor(i / GRID_COLS);
        const x = c * GRID_STEP_X + Math.random() * GRID_JITTER;
        const y = r * GRID_STEP_Y + Math.random() * GRID_JITTER;

        initialSlots.push({
          id: i,
          listing: getNextListing(shuffledListings, listIndexRef),
          opacity: Math.random() * REDUCED_OPACITY_SPREAD + REDUCED_OPACITY_MIN,
          x: Math.min(x, GRID_MAX_XY),
          y: Math.min(y, GRID_MAX_XY),
          rotX: Math.random() * REDUCED_TILT_SPREAD - REDUCED_TILT_OFFSET,
          rotY: Math.random() * REDUCED_TILT_SPREAD - REDUCED_TILT_OFFSET,
          scale: REDUCED_SCALE_BASE + Math.random() * REDUCED_SCALE_SPREAD,
          animationDuration: 0,
          animationDelay: 0,
        });
      }
    } else {
      for (let i = 0; i < numCards; i += 1) {
        const props = getRandomProps();
        const { scale, opacity } = computeSlotVisuals(props.x, props.y);

        initialSlots.push({
          id: i,
          listing: getNextListing(shuffledListings, listIndexRef),
          opacity,
          ...props,
          scale,
        });
      }
    }

    poolRef.current = initialSlots;
    setSlots([...initialSlots]);
  }, [shuffledListings, isReducedMotion, poolRef, listIndexRef, setSlots]);
}

interface TimerRecyclingArgs {
  readonly isVisible: boolean;
  readonly isReducedMotion: boolean;
  readonly shuffledListings: AuthListingItem[];
  readonly poolRef: React.MutableRefObject<CardSlot[]>;
  readonly listIndexRef: React.MutableRefObject<number>;
  readonly setSlots: (slots: CardSlot[]) => void;
}

function useTimerRecycling({
  isVisible,
  isReducedMotion,
  shuffledListings,
  poolRef,
  listIndexRef,
  setSlots,
}: TimerRecyclingArgs): void {
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    if (shuffledListings.length === 0 || isReducedMotion) {
      return;
    }

    const cycleCard = (id: number): void => {
      const current = poolRef.current[id];
      if (!current) {
        return;
      }
      poolRef.current[id] = { ...current, opacity: 0 };
      setSlots([...poolRef.current]);
      timersRef.current.set(
        id,
        setTimeout(
          () =>
            scheduleCycleAfterSwap({
              id,
              poolRef,
              shuffledListings,
              listIndexRef,
              timersRef,
              setSlots,
              cycleCard,
            }),
          FADE_OUT_MS,
        ),
      );
    };

    if (isVisible) {
      startVisibleTimers(poolRef, timersRef, cycleCard);
    } else {
      clearAllTimers(timersRef);
    }

    return () => clearAllTimers(timersRef);
  }, [isVisible, isReducedMotion, shuffledListings, poolRef, listIndexRef, setSlots]);
}

export function AuthListingsCanvas(): JSX.Element | null {
  const { data } = useAuthListings();
  const isReducedMotion = useReducedMotion();
  const isVisible = useTabVisibility();

  const { shuffledListings, slots, setSlots, poolRef, listIndexRef } = useCanvasState(data);

  useCanvasInitialization({ shuffledListings, isReducedMotion, poolRef, listIndexRef, setSlots });
  useTimerRecycling({
    isVisible,
    isReducedMotion,
    shuffledListings,
    poolRef,
    listIndexRef,
    setSlots,
  });

  if (slots.length === 0) {
    return null;
  }

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden"
      style={{ contain: 'layout style paint' }}
    >
      <style>{STYLES}</style>
      {slots.map((slot) => (
        <div
          key={slot.id}
          className="absolute transition-opacity duration-500 ease-in-out will-change-[transform,opacity]"
          style={{
            left: `${slot.x}%`,
            top: `${slot.y}%`,
            opacity: slot.opacity,
            animation: isReducedMotion
              ? 'none'
              : `auth-canvas-drift ${slot.animationDuration}s linear infinite`,
            animationDelay: `${slot.animationDelay}s`,
            animationPlayState: isVisible ? 'running' : 'paused',
          }}
        >
          <div
            className="will-change-transform"
            style={{
              transform: `perspective(1000px) rotateY(${slot.rotY}deg) rotateX(${slot.rotX}deg) scale(${slot.scale})`,
              // Apply more blur to cards that are smaller/further back based on scale
              filter:
                slot.scale < BLUR_SCALE_THRESHOLD
                  ? `blur(${isReducedMotion ? 0 : Math.max(0, (BLUR_SCALE_THRESHOLD - slot.scale) * BLUR_INTENSITY)}px)`
                  : 'none',
            }}
          >
            <AuthListingCard listing={slot.listing} className="w-[320px] max-w-[90vw]" />
          </div>
        </div>
      ))}
    </div>
  );
}
