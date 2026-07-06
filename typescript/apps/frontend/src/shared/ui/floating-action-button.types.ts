import type { ElementType } from 'react';

interface FloatingAction {
  /** Unique identifier for the action. */
  readonly id: string;
  /** Display label for the action. */
  readonly label: string;
  /** Lucide icon component. */
  readonly icon: ElementType;
  /** Click handler. */
  readonly onClick: () => void;
  /** Whether this action is emphasized (uses accent color). */
  readonly emphasis?: boolean;
  /** Whether this action is disabled. */
  readonly disabled?: boolean;
  /** Whether this action is loading. */
  readonly loading?: boolean;
}

type FABSize = 'sm' | 'md' | 'lg';

interface FloatingActionButtonProps {
  /** Array of actions to display in the FAB menu. */
  readonly actions: FloatingAction[];
  /** Icon to show when FAB is closed. */
  readonly triggerIcon: ElementType;
  /** Accessible label for the trigger button. */
  readonly triggerLabel: string;
  /** Additional class names for the root container. */
  readonly className?: string;
  /** Whether to close menu on scroll (default: true). */
  readonly closeOnScroll?: boolean;
  /** Position of the FAB. */
  readonly position?: 'bottom-right' | 'bottom-left';
  /** Size of the FAB trigger button. */
  readonly size?: FABSize;
}

export type { FABSize, FloatingAction, FloatingActionButtonProps };
