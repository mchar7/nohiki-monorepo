import { useAppStore } from '@/shared/model/appStore.ts';

type Density = 'compact' | 'comfortable' | 'spacious';

interface DensityClasses {
  readonly gap: string;
  readonly padding: string;
  readonly text: string;
}

const DENSITY_CLASSES: Record<Density, DensityClasses> = {
  compact: { gap: 'gap-1', padding: 'py-1 px-2', text: 'text-sm' },
  comfortable: { gap: 'gap-2', padding: 'py-2 px-3', text: 'text-sm' },
  spacious: { gap: 'gap-3', padding: 'py-3 px-4', text: 'text-base' },
};

interface UseDensityResult {
  readonly density: Density;
  readonly setDensity: (d: Density) => void;
  readonly classes: DensityClasses;
  /** Returns one of three values based on the current density setting.
   *  Useful for inline class selection: `pick('gap-2', 'gap-4', 'gap-6')` */
  readonly pick: <T>(compact: T, comfortable: T, spacious: T) => T;
}

/**
 * Reads and writes display density from the global Zustand store.
 *
 * Returns current density, setter, corresponding Tailwind class map,
 * and a `pick` helper for inline density-based value selection.
 */
function useDensity(): UseDensityResult {
  const density = useAppStore((s) => s.density);
  const setDensity = useAppStore((s) => s.setDensity);

  const pick = <T>(compact: T, comfortable: T, spacious: T): T => {
    switch (density) {
      case 'compact':
        return compact;
      case 'spacious':
        return spacious;
      default:
        return comfortable;
    }
  };

  return { density, setDensity, classes: DENSITY_CLASSES[density], pick };
}

export { DENSITY_CLASSES, type Density, useDensity };
