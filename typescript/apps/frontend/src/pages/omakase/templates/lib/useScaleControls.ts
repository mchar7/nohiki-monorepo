import type { PreviewConfig, PreviewState, ScaleState } from '../model/index.ts';
import { calculateFitScale, clampScale, getNextScaleStep } from './preview-calculations.ts';

/** Percentage representing 100% / actual size scale */
const ACTUAL_SCALE_PERCENT: number = 100;

interface ScaleControls {
  setScaleMode: (mode: ScaleState['mode']) => void;
  setCustomScale: (percentage: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
}

/**
 * Provides scale manipulation callbacks for the preview image.
 * Encapsulates fit/actual/custom modes and zoom step logic.
 */
export function useScaleControls(
  config: PreviewConfig,
  setPreviewState: React.Dispatch<React.SetStateAction<PreviewState>>,
): ScaleControls {
  const setScaleMode = (mode: ScaleState['mode']): void => {
    setPreviewState((prev) => {
      const newScale = { ...prev.scale, mode };

      if (mode === 'fit' && prev.imageNaturalSize) {
        newScale.percentage = calculateFitScale(prev.imageNaturalSize, prev.containerSize);
      } else if (mode === 'actual') {
        newScale.percentage = ACTUAL_SCALE_PERCENT;
      }

      return { ...prev, scale: newScale };
    });
  };

  const setCustomScale = (percentage: number): void => {
    const clamped = clampScale(percentage, config);
    setPreviewState((prev) => ({
      ...prev,
      scale: { ...prev.scale, mode: 'custom', percentage: clamped },
    }));
  };

  const zoomIn = (): void => {
    setPreviewState((prev) => ({
      ...prev,
      scale: {
        ...prev.scale,
        mode: 'custom',
        percentage: clampScale(
          getNextScaleStep(prev.scale.percentage, 'in', config.scaleStep),
          config,
        ),
      },
    }));
  };

  const zoomOut = (): void => {
    setPreviewState((prev) => ({
      ...prev,
      scale: {
        ...prev.scale,
        mode: 'custom',
        percentage: clampScale(
          getNextScaleStep(prev.scale.percentage, 'out', config.scaleStep),
          config,
        ),
      },
    }));
  };

  return { setScaleMode, setCustomScale, zoomIn, zoomOut };
}
