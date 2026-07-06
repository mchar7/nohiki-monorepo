import type { ReactNode } from 'react';

interface OverflowAction {
  readonly label: string;
  readonly icon?: ReactNode;
  readonly onClick: () => void;
}

interface ActionBarProps {
  /** Prominent CTA rendered at the start of the bar. */
  readonly primaryAction?: ReactNode;
  /** Icon buttons or small actions shown inline on desktop, collapsed on mobile. */
  readonly secondaryActions?: readonly ReactNode[];
  /** Items rendered inside a ResponsiveMenu overflow trigger. */
  readonly overflowActions?: readonly OverflowAction[];
}

export type { ActionBarProps, OverflowAction };
