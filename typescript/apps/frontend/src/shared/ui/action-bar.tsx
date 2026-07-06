import { MoreVertical } from 'lucide-react';
import { type JSX, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useIsMobileLayout } from '@/shared/lib/index.ts';
import type { ActionBarProps } from './action-bar.types.ts';
import { Button } from './button.tsx';
import { ResponsiveMenu, ResponsiveMenuItem } from './responsive-menu.tsx';

/**
 * Horizontal action bar with slot architecture for detail views.
 *
 * Renders primary action prominently, secondary actions inline on desktop
 * (collapsed into overflow on mobile), and overflow actions in a ResponsiveMenu.
 */
function ActionBar({
  primaryAction,
  secondaryActions,
  overflowActions,
}: ActionBarProps): JSX.Element {
  const isMobile = useIsMobileLayout();
  const [menuOpen, setMenuOpen] = useState(false);
  const { t } = useTranslation(['common']);

  const hasOverflow = (overflowActions?.length ?? 0) > 0;
  const hasSecondary = (secondaryActions?.length ?? 0) > 0;
  const showOverflowMenu = hasOverflow || (isMobile && hasSecondary);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {primaryAction}

      {!isMobile && hasSecondary
        ? secondaryActions?.map((action, idx) => (
            <span key={`secondary-${idx.toString()}`}>{action}</span>
          ))
        : null}

      {showOverflowMenu ? (
        <ResponsiveMenu
          open={menuOpen}
          onOpenChange={setMenuOpen}
          title={t('common:a11y.more')}
          trigger={
            <Button variant="ghost" size="icon" className="size-9">
              <MoreVertical className="size-4" aria-hidden="true" />
              <span className="sr-only">{t('common:a11y.more')}</span>
            </Button>
          }
        >
          {isMobile && hasSecondary
            ? secondaryActions?.map((action, idx) => (
                <span key={`mobile-secondary-${idx.toString()}`}>{action}</span>
              ))
            : null}
          {overflowActions?.map((action) => (
            <ResponsiveMenuItem key={action.label} icon={action.icon} onClick={action.onClick}>
              {action.label}
            </ResponsiveMenuItem>
          ))}
        </ResponsiveMenu>
      ) : null}
    </div>
  );
}

export { ActionBar };
