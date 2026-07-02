import { Link, useLocation } from '@tanstack/react-router';
import type { LucideIcon } from 'lucide-react';
import { Briefcase, FileText, Home, User } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { ROUTE_PATHS } from '@/shared/config/index.ts';
import { cn } from '@/shared/lib';
import { useSidebar } from '@/shared/ui/sidebar.tsx';

interface BottomNavItem {
  readonly titleKey: string;
  readonly icon: LucideIcon;
  readonly href: string;
  readonly end?: boolean;
}

/** Primary routes shown in the mobile bottom navigation bar. */
const BOTTOM_NAV_ITEMS: readonly BottomNavItem[] = [
  { titleKey: 'sidebar.dashboard', icon: Home, href: ROUTE_PATHS.HOME, end: true },
  { titleKey: 'sidebar.jobs.title', icon: Briefcase, href: ROUTE_PATHS.JOBS.LIST },
  { titleKey: 'sidebar.profiles.title', icon: User, href: ROUTE_PATHS.PROFILES.LIST },
  { titleKey: 'sidebar.documents.title', icon: FileText, href: ROUTE_PATHS.DOCUMENTS.LIST },
  { titleKey: 'sidebar.account', icon: User, href: ROUTE_PATHS.ACCOUNT.SETTINGS },
] as const;

function isActive(pathname: string, item: BottomNavItem): boolean {
  return item.end ? pathname === item.href : pathname.startsWith(item.href);
}

function BottomNavLink({
  item,
  pathname,
}: {
  readonly item: BottomNavItem;
  readonly pathname: string;
}): JSX.Element {
  const { t } = useTranslation('navigation');
  const active = isActive(pathname, item);
  const Icon = item.icon;

  return (
    <Link
      to={item.href}
      className={cn(
        'flex flex-1 flex-col items-center gap-0.5 py-2 text-xs transition-colors',
        active ? 'text-primary' : 'text-muted-foreground',
      )}
      aria-current={active ? 'page' : undefined}
    >
      <Icon className="size-5" />
      <span className="truncate">{t(item.titleKey)}</span>
    </Link>
  );
}

/** Fixed bottom navigation bar, visible only on mobile (below md breakpoint). */
function BottomNav(): JSX.Element | null {
  const { t } = useTranslation('common');
  const { pathname } = useLocation();
  const { openMobile } = useSidebar();

  // Hide when the mobile sidebar Sheet is open so it doesn't obscure the Sheet footer.
  if (openMobile) {
    return null;
  }
  return (
    <nav
      aria-label={t('a11y.bottomNav')}
      className="fixed inset-x-0 bottom-0 z-50 border-t bg-background/95 backdrop-blur supports-backdrop-filter:bg-background/60 md:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <div className="flex items-center justify-around">
        {BOTTOM_NAV_ITEMS.map((item) => (
          <BottomNavLink key={item.href} item={item} pathname={pathname} />
        ))}
      </div>
    </nav>
  );
}

export { BottomNav };
