import type { AuthListingItem } from '../model/types';

export interface CardSlot {
  id: number;
  listing: AuthListingItem;
  opacity: number;
  x: number;
  y: number;
  rotX: number;
  rotY: number;
  scale: number;
  animationDuration: number;
  animationDelay: number;
}

export const MAX_CARDS = 30;
const ANIMATION_DURATION_MIN = 20;
const ANIMATION_DURATION_MAX = 40;
const RECYCLE_MIN_MS = 15_000;
const RECYCLE_MAX_MS = 30_000;
export const FADE_OUT_MS = 500;

// Card position, rotation, and scale distribution
const POS_MIN = 5;
const POS_SPREAD = 70;
const ROT_MIN = -20;
const ROT_SPREAD = 40;
const SCALE_MIN = 0.7;
const SCALE_SPREAD = 0.4;
const OPACITY_MIN = 0.2;
const OPACITY_SPREAD = 0.6;
const OPACITY_FLOOR = 0.1;
const OPACITY_CEILING = 1;
const SCALE_DIST_WEIGHT = 0.5;
const OPACITY_DIST_WEIGHT = 0.7;
const JITTER_RANGE = 0.1;
const JITTER_OFFSET = 0.05;
export const BLUR_SCALE_THRESHOLD = 0.85;
export const BLUR_INTENSITY = 10;

export const REDUCED_CARDS = 12;
export const GRID_COLS = 4;
const GRID_ROWS = 3;
const GRID_PERCENT = 100;
export const GRID_STEP_X: number = GRID_PERCENT / GRID_COLS;
export const GRID_STEP_Y: number = GRID_PERCENT / GRID_ROWS;
export const GRID_MAX_XY = 80;
export const GRID_JITTER = 10;
export const REDUCED_OPACITY_MIN = 0.4;
export const REDUCED_OPACITY_SPREAD = 0.4;
export const REDUCED_TILT_SPREAD = 30;
export const REDUCED_TILT_OFFSET = 15;
export const REDUCED_SCALE_BASE = 0.85;
export const REDUCED_SCALE_SPREAD = 0.15;

const CENTER_PERCENT = 50;

function calculateDistance(x: number, y: number): number {
  const dx = (x - CENTER_PERCENT) / CENTER_PERCENT;
  const dy = (y - CENTER_PERCENT) / CENTER_PERCENT;
  return Math.min(1, Math.sqrt(dx * dx + dy * dy));
}

export function shuffleArray<T>(array: T[]): T[] {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    const temp = shuffled[i] as T;
    shuffled[i] = shuffled[j] as T;
    shuffled[j] = temp;
  }
  return shuffled;
}

/** Round-robin through shuffled listings. Callers must ensure the array is non-empty. */
export function getNextListing(
  shuffledListings: AuthListingItem[],
  listIndexRef: React.MutableRefObject<number>,
): AuthListingItem {
  const index = listIndexRef.current % shuffledListings.length;
  listIndexRef.current += 1;
  return shuffledListings[index] as AuthListingItem;
}

export function getRandomProps(): Omit<CardSlot, 'id' | 'listing' | 'opacity'> {
  return {
    x: Math.random() * POS_SPREAD + POS_MIN,
    y: Math.random() * POS_SPREAD + POS_MIN,
    rotX: Math.random() * ROT_SPREAD + ROT_MIN,
    rotY: Math.random() * ROT_SPREAD + ROT_MIN,
    scale: 1, // Placeholder; callers override with distance-based value
    animationDuration:
      Math.random() * (ANIMATION_DURATION_MAX - ANIMATION_DURATION_MIN) + ANIMATION_DURATION_MIN,
    animationDelay: -(Math.random() * ANIMATION_DURATION_MAX),
  };
}

/** Computes distance-based scale and clamped opacity for a card slot position. */
export function computeSlotVisuals(x: number, y: number): { scale: number; opacity: number } {
  const dist = calculateDistance(x, y);
  const scale =
    SCALE_MIN +
    SCALE_SPREAD * (1 - dist * SCALE_DIST_WEIGHT) +
    (Math.random() * JITTER_RANGE - JITTER_OFFSET);
  const opacity =
    OPACITY_MIN +
    OPACITY_SPREAD * (1 - dist * OPACITY_DIST_WEIGHT) +
    (Math.random() * JITTER_RANGE - JITTER_OFFSET);
  return { scale, opacity: Math.max(OPACITY_FLOOR, Math.min(OPACITY_CEILING, opacity)) };
}

/** Creates a new card slot with fresh random position, visuals, and the next listing. */
function createSwappedSlot(
  existing: CardSlot,
  shuffledListings: AuthListingItem[],
  listIndexRef: React.MutableRefObject<number>,
): CardSlot {
  const props = getRandomProps();
  const { scale, opacity } = computeSlotVisuals(props.x, props.y);
  return {
    ...existing,
    ...props,
    scale,
    listing: getNextListing(shuffledListings, listIndexRef),
    opacity,
  };
}

interface CycleCardArgs {
  id: number;
  poolRef: React.MutableRefObject<CardSlot[]>;
  shuffledListings: AuthListingItem[];
  listIndexRef: React.MutableRefObject<number>;
  timersRef: React.MutableRefObject<Map<number, ReturnType<typeof setTimeout>>>;
  setSlots: (slots: CardSlot[]) => void;
  cycleCard: (id: number) => void;
}

export function scheduleCycleAfterSwap({
  id,
  poolRef,
  shuffledListings,
  listIndexRef,
  timersRef,
  setSlots,
  cycleCard,
}: CycleCardArgs): void {
  const slot = poolRef.current[id];
  if (!slot) {
    return;
  }
  poolRef.current[id] = createSwappedSlot(slot, shuffledListings, listIndexRef);
  setSlots([...poolRef.current]);

  const nextDuration = Math.random() * (RECYCLE_MAX_MS - RECYCLE_MIN_MS) + RECYCLE_MIN_MS;
  timersRef.current.set(
    id,
    setTimeout(() => cycleCard(id), nextDuration),
  );
}

export function startVisibleTimers(
  poolRef: React.MutableRefObject<CardSlot[]>,
  timersRef: React.MutableRefObject<Map<number, ReturnType<typeof setTimeout>>>,
  cycleCard: (id: number) => void,
): void {
  for (const slot of poolRef.current) {
    if (!timersRef.current.has(slot.id)) {
      const delay = slot.opacity === 0 ? 0 : Math.random() * RECYCLE_MIN_MS;
      timersRef.current.set(
        slot.id,
        setTimeout(() => cycleCard(slot.id), delay),
      );
    }
  }
}

export function clearAllTimers(
  timersRef: React.MutableRefObject<Map<number, ReturnType<typeof setTimeout>>>,
): void {
  for (const timerId of timersRef.current.values()) {
    clearTimeout(timerId);
  }
  timersRef.current.clear();
}

export const STYLES = `
  @keyframes auth-canvas-drift {
    0% { transform: translateY(15vh); }
    100% { transform: translateY(-15vh); }
  }
`;
