import type { ReactNode } from 'react';

interface ResponsiveMenuProps {
  /** Controls whether the menu is open. */
  readonly open: boolean;
  /** Callback when open state changes. */
  readonly onOpenChange: (open: boolean) => void;
  /** Title shown in BottomSheet header on mobile. */
  readonly title: string;
  /** Trigger element (typically an icon button). Rendered in both modes. */
  readonly trigger: ReactNode;
  /** Menu items - use ResponsiveMenuItem and ResponsiveMenuSeparator. */
  readonly children: ReactNode;
  /** DropdownMenu alignment (default: 'end'). */
  readonly align?: 'start' | 'center' | 'end';
}

interface ResponsiveMenuItemProps {
  /** Icon to display before the label (optional). */
  readonly icon?: ReactNode;
  /** Label text. */
  readonly children: ReactNode;
  /** Destructive styling (red text). Default: 'default'. */
  readonly variant?: 'default' | 'destructive';
  /** Disabled state. */
  readonly disabled?: boolean;
  /** Click handler - menu closes automatically after invocation. */
  readonly onClick: () => void;
  /** Extra className applied to the root element. */
  readonly className?: string;
}

export type { ResponsiveMenuItemProps, ResponsiveMenuProps };
