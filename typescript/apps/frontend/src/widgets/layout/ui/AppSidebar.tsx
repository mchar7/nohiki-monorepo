import { useAccount } from '@features/account';
import { Link, useLocation } from '@tanstack/react-router';
import {
  ChevronRight,
  ChevronsUpDown,
  HelpCircle,
  LogOut,
  Monitor,
  Moon,
  Scale,
  Settings,
  Sun,
  User,
} from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { useLogout } from '@/shared/api/index.ts';
import { MAIN_NAVIGATION, type NavItem, ROUTE_PATHS } from '@/shared/config/index.ts';
import { useTheme } from '@/shared/lib/index.ts';
import { Avatar, AvatarFallback } from '@/shared/ui/avatar.tsx';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/ui/collapsible.tsx';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/ui/dropdown-menu.tsx';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from '@/shared/ui/sidebar.tsx';
import { NavBadge } from './nav-badge.tsx';

const APP_INITIAL = 'N';
const SECONDARY_NAV = [{ key: 'documentation', icon: HelpCircle }] as const;

function isActive(pathname: string, item: NavItem): boolean {
  if (!item.href) {
    return false;
  }
  return item.end ? pathname === item.href : pathname.startsWith(item.href);
}

function NavItemWithChildren({
  item,
  pathname,
}: {
  readonly item: NavItem;
  readonly pathname: string;
}): JSX.Element {
  const { t } = useTranslation('navigation');
  const childActive = item.children?.some((child) => isActive(pathname, child));

  return (
    <Collapsible defaultOpen={childActive ?? false} asChild={true}>
      <SidebarMenuItem>
        <CollapsibleTrigger asChild={true}>
          <SidebarMenuButton className="w-full">
            <item.icon className="size-4" aria-hidden="true" />
            <span>{t(item.titleKey as 'sidebar.dashboard')}</span>
            <ChevronRight
              className="ml-auto size-4 transition-transform group-data-[state=open]/collapsible:rotate-90"
              aria-hidden="true"
            />
          </SidebarMenuButton>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <SidebarMenuSub>
            {item.children?.map((child) => (
              <SidebarMenuSubItem key={child.titleKey}>
                <SidebarMenuSubButton asChild={true} isActive={isActive(pathname, child)}>
                  <Link to={child.href ?? '#'}>
                    <child.icon className="size-4" aria-hidden="true" />
                    <span>{t(child.titleKey as 'sidebar.dashboard')}</span>
                  </Link>
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            ))}
          </SidebarMenuSub>
        </CollapsibleContent>
      </SidebarMenuItem>
    </Collapsible>
  );
}

function NavItemLink({
  item,
  pathname,
}: {
  readonly item: NavItem;
  readonly pathname: string;
}): JSX.Element {
  const { t } = useTranslation('navigation');

  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild={true} isActive={isActive(pathname, item)}>
        <Link to={item.href ?? '#'}>
          <item.icon className="size-4" aria-hidden="true" />
          <span>{t(item.titleKey as 'sidebar.dashboard')}</span>
        </Link>
      </SidebarMenuButton>
      <NavBadge count={item.badge} />
    </SidebarMenuItem>
  );
}

function ThemeToggle(): JSX.Element {
  const { theme, setTheme } = useTheme();
  const { t } = useTranslation('common');

  const handleSetLight = (): void => setTheme('light');
  const handleSetDark = (): void => setTheme('dark');
  const handleSetSystem = (): void => setTheme('system');

  return (
    <div className="flex w-full gap-0.5 rounded-md border bg-muted/50 p-0.5">
      <button
        type="button"
        onClick={handleSetLight}
        aria-label={t('theme.light')}
        className="flex flex-1 items-center justify-center rounded p-1.5 transition-colors hover:bg-background data-[active=true]:bg-background data-[active=true]:shadow-sm"
        data-active={theme === 'light'}
      >
        <Sun className="size-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={handleSetDark}
        aria-label={t('theme.dark')}
        className="flex flex-1 items-center justify-center rounded p-1.5 transition-colors hover:bg-background data-[active=true]:bg-background data-[active=true]:shadow-sm"
        data-active={theme === 'dark'}
      >
        <Moon className="size-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={handleSetSystem}
        aria-label={t('theme.system')}
        className="flex flex-1 items-center justify-center rounded p-1.5 transition-colors hover:bg-background data-[active=true]:bg-background data-[active=true]:shadow-sm"
        data-active={theme === 'system'}
      >
        <Monitor className="size-4" aria-hidden="true" />
      </button>
    </div>
  );
}

function UserMenu(): JSX.Element {
  const { t } = useTranslation(['common', 'auth']);
  const { isMobile } = useSidebar();
  const { data: account } = useAccount();
  const logoutMutation = useLogout();

  const getInitials = (): string => {
    if (account?.display_name) {
      return account.display_name.charAt(0).toUpperCase();
    }

    if (account?.email) {
      return account.email.charAt(0).toUpperCase();
    }

    return 'U';
  };

  const userInitial = getInitials();

  const handleLogout = (): void => {
    logoutMutation.mutate();
  };

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild={true}>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              aria-label={t('a11y.userMenu')}
              onClick={(e: React.MouseEvent) => e.stopPropagation()}
            >
              <Avatar className="size-8">
                <AvatarFallback>{userInitial}</AvatarFallback>
              </Avatar>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{t('auth:account.profile')}</span>
                <span className="truncate text-muted-foreground text-xs">
                  {t('common:sidebar.preferencesTheme')}
                </span>
              </div>
              <ChevronsUpDown className="ml-auto size-4" aria-hidden="true" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-56 rounded-lg"
            side={isMobile ? 'bottom' : 'right'}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuLabel>{t('common:sidebar.quickSettings')}</DropdownMenuLabel>
            <div className="px-2 pb-2">
              <ThemeToggle />
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild={true}>
              <Link to={ROUTE_PATHS.ACCOUNT.SETTINGS}>
                <User className="size-4" aria-hidden="true" />
                {t('auth:account.profile')}
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild={true}>
              <Link to={ROUTE_PATHS.SETTINGS}>
                <Settings className="size-4" aria-hidden="true" />
                {t('common:nav.settings')}
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild={true}>
              <Link to={ROUTE_PATHS.LICENSES}>
                <Scale className="size-4" aria-hidden="true" />
                {t('common:features.licenses')}
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={handleLogout}
              disabled={logoutMutation.isPending}
              className="text-destructive focus:text-destructive"
            >
              <LogOut className="size-4" aria-hidden="true" />
              {logoutMutation.isPending ? t('auth:session.signingOut') : t('auth:actions.signOut')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

export function AppSidebar(): JSX.Element {
  const { t } = useTranslation(['common', 'navigation']);
  const { t: tNav } = useTranslation('navigation');
  const { pathname } = useLocation();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild={true}>
              <Link to={ROUTE_PATHS.HOME}>
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <span className="font-bold text-sm">{APP_INITIAL}</span>
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">{t('common:appName')}</span>
                  <span className="truncate text-muted-foreground text-xs">
                    {t('common:appTagline')}
                  </span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>{tNav('sidebar.navigation')}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {MAIN_NAVIGATION.map((item) =>
                item.children ? (
                  <NavItemWithChildren key={item.titleKey} item={item} pathname={pathname} />
                ) : (
                  <NavItemLink key={item.titleKey} item={item} pathname={pathname} />
                ),
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="mt-auto">
          <SidebarGroupContent>
            <SidebarMenu>
              {SECONDARY_NAV.map((item) => (
                <SidebarMenuItem key={item.key}>
                  <SidebarMenuButton tooltip={tNav(`secondary.${item.key}`)} asChild={true}>
                    <a href={t('common:sidebar.docsUrl')} target="_blank" rel="noopener noreferrer">
                      <item.icon className="size-4" />
                      <span>{tNav(`secondary.${item.key}`)}</span>
                    </a>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <UserMenu />
      </SidebarFooter>
    </Sidebar>
  );
}
