import type { JSX } from 'react';
import { SidebarMenuBadge } from '@/shared/ui/sidebar.tsx';

const MAX_BADGE_DISPLAY = 99;

/**
 * Renders a sidebar badge for a nav item count.
 *
 * Returns null when count is undefined, zero, negative, or NaN; only positive
 * integers produce a visible badge. Caps display at '99+' to avoid overflow.
 */
export function NavBadge({ count }: { readonly count: number | undefined }): JSX.Element | null {
  if (count === undefined || count <= 0 || !Number.isFinite(count)) {
    return null;
  }

  return <SidebarMenuBadge>{count > MAX_BADGE_DISPLAY ? '99+' : String(count)}</SidebarMenuBadge>;
}
