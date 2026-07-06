interface ScoreBadgeProps {
  /** Score value in the 0–100 range (already an integer, NOT a 0–1 float). */
  readonly score: number;
  readonly className?: string;
}

export type { ScoreBadgeProps };
