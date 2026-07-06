interface SaveToggleProps {
  readonly isSaved: boolean;
  readonly onToggle: () => void;
  readonly disabled?: boolean;
  /** Tooltip shown when the toggle is disabled (e.g. "Match with a profile to save"). */
  readonly disabledTooltip?: string;
}

export type { SaveToggleProps };
