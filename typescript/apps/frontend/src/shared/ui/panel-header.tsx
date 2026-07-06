import type { LucideIcon } from 'lucide-react';
import type { JSX, ReactNode } from 'react';

interface PanelHeaderProps {
  /** Panel title text */
  readonly title: string;
  /** Optional Lucide icon to display before the title */
  readonly icon?: LucideIcon;
  /** Action buttons or controls to display on the right */
  readonly actions?: ReactNode;
  /** Compact mode for smaller panels */
  readonly compact?: boolean;
  /** Whether to show the header - useful for hiding in fullscreen dialogs */
  readonly visible?: boolean;
}

/**
 * Consistent header component for panels, cards, and sections.
 * Supports an optional icon that uses the muted-foreground color for consistency.
 */
export function PanelHeader({
  title,
  icon: Icon,
  actions,
  compact = false,
  visible = true,
}: PanelHeaderProps): JSX.Element | null {
  if (!visible) {
    return null;
  }

  return (
    <div className={`shrink-0 border-b bg-muted/20 ${compact ? 'h-10 px-3' : 'h-10 px-4'}`}>
      <div className="flex h-full min-w-0 items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          {Icon ? <Icon className="size-4 text-muted-foreground" /> : null}
          <span className="font-medium text-sm">{title}</span>
        </div>
        {actions ? <div className="flex shrink-0 gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}
