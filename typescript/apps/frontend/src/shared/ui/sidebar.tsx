import { cn } from '@shared/lib/index.ts';
import { PanelLeftIcon } from 'lucide-react';
import type { CSSProperties, JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from './button.tsx';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from './sheet.tsx';
import { SIDEBAR_WIDTH_MOBILE, useSidebar } from './sidebar-context.tsx';

function SidebarNonCollapsible({
  className,
  children,
  ...props
}: React.ComponentProps<'div'>): JSX.Element {
  return (
    <div
      data-slot="sidebar"
      className={cn(
        'flex h-full w-(--sidebar-width) flex-col bg-sidebar text-sidebar-foreground',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

function SidebarMobile({
  side,
  openMobile,
  setOpenMobile,
  children,
  ...props
}: React.ComponentProps<'div'> & {
  side: 'left' | 'right';
  openMobile: boolean;
  setOpenMobile: (open: boolean) => void;
}): JSX.Element {
  const { t } = useTranslation('common');

  return (
    <Sheet open={openMobile} onOpenChange={setOpenMobile} {...props}>
      <SheetContent
        data-sidebar="sidebar"
        data-slot="sidebar"
        data-mobile="true"
        className="w-(--sidebar-width) bg-sidebar p-0 text-sidebar-foreground [&>button]:hidden"
        style={{ '--sidebar-width': SIDEBAR_WIDTH_MOBILE } as CSSProperties}
        side={side}
      >
        <SheetHeader className="sr-only">
          <SheetTitle>{t('a11y.sidebarTitle')}</SheetTitle>
          <SheetDescription>{t('a11y.sidebarDescription')}</SheetDescription>
        </SheetHeader>
        <div
          className="flex h-full w-full flex-col"
          style={{ paddingTop: 'env(safe-area-inset-top)' }}
        >
          {children}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function SidebarDesktop({
  side,
  variant,
  state,
  collapsible,
  className,
  children,
  ...props
}: React.ComponentProps<'div'> & {
  side: 'left' | 'right';
  variant: 'sidebar' | 'floating' | 'inset';
  state: 'expanded' | 'collapsed';
  collapsible: 'offcanvas' | 'icon' | 'none';
}): JSX.Element {
  return (
    <div
      className="group peer hidden text-sidebar-foreground md:block"
      data-state={state}
      data-collapsible={state === 'collapsed' ? collapsible : ''}
      data-variant={variant}
      data-side={side}
      data-slot="sidebar"
    >
      <div
        data-slot="sidebar-gap"
        className={cn(
          'relative w-(--sidebar-width) bg-transparent transition-[width] duration-200 ease-linear',
          'group-data-[collapsible=offcanvas]:w-0',
          'group-data-[side=right]:rotate-180',
          variant === 'floating' || variant === 'inset'
            ? 'group-data-[collapsible=icon]:w-[calc(var(--sidebar-width-icon)+(--spacing(4)))]'
            : 'group-data-[collapsible=icon]:w-(--sidebar-width-icon)',
        )}
      />
      <div
        data-slot="sidebar-container"
        className={cn(
          'fixed inset-y-0 z-10 hidden h-svh w-(--sidebar-width) transition-[left,right,width] duration-200 ease-linear md:flex',
          side === 'left'
            ? 'left-0 group-data-[collapsible=offcanvas]:left-[calc(var(--sidebar-width)*-1)]'
            : 'right-0 group-data-[collapsible=offcanvas]:right-[calc(var(--sidebar-width)*-1)]',
          variant === 'floating' || variant === 'inset'
            ? 'p-2 group-data-[collapsible=icon]:w-[calc(var(--sidebar-width-icon)+(--spacing(4))+2px)]'
            : 'group-data-[collapsible=icon]:w-(--sidebar-width-icon) group-data-[side=left]:border-r group-data-[side=right]:border-l',
          className,
        )}
        {...props}
      >
        <div
          data-sidebar="sidebar"
          data-slot="sidebar-inner"
          className="flex h-full w-full flex-col bg-sidebar group-data-[variant=floating]:rounded-lg group-data-[variant=floating]:border group-data-[variant=floating]:border-sidebar-border group-data-[variant=floating]:shadow-sm"
        >
          {children}
        </div>
      </div>
    </div>
  );
}

function Sidebar({
  side = 'left',
  variant = 'sidebar',
  collapsible = 'offcanvas',
  className,
  children,
  ...props
}: React.ComponentProps<'div'> & {
  side?: 'left' | 'right';
  variant?: 'sidebar' | 'floating' | 'inset';
  collapsible?: 'offcanvas' | 'icon' | 'none';
}): JSX.Element {
  const { isMobile, state, openMobile, setOpenMobile } = useSidebar();

  if (collapsible === 'none') {
    return (
      <SidebarNonCollapsible className={className} {...props}>
        {children}
      </SidebarNonCollapsible>
    );
  }

  if (isMobile) {
    return (
      <SidebarMobile side={side} openMobile={openMobile} setOpenMobile={setOpenMobile} {...props}>
        {children}
      </SidebarMobile>
    );
  }

  return (
    <SidebarDesktop
      side={side}
      variant={variant}
      state={state}
      collapsible={collapsible}
      className={className}
      {...props}
    >
      {children}
    </SidebarDesktop>
  );
}

function SidebarTrigger({
  className,
  onClick,
  ...props
}: React.ComponentProps<typeof Button>): JSX.Element {
  const { toggleSidebar } = useSidebar();
  const { t } = useTranslation('common');

  const handleClick = (event: React.MouseEvent<HTMLButtonElement>): void => {
    onClick?.(event);
    toggleSidebar();
  };

  return (
    <Button
      data-sidebar="trigger"
      data-slot="sidebar-trigger"
      variant="ghost"
      size="icon"
      className={cn('size-7', className)}
      onClick={handleClick}
      {...props}
    >
      <PanelLeftIcon />
      <span className="sr-only">{t('a11y.toggleSidebar')}</span>
    </Button>
  );
}

export function SidebarRail({ className, ...props }: React.ComponentProps<'button'>): JSX.Element {
  const { toggleSidebar } = useSidebar();
  const { t } = useTranslation('common');

  return (
    <button
      data-sidebar="rail"
      data-slot="sidebar-rail"
      aria-label={t('a11y.toggleSidebar')}
      tabIndex={0}
      onClick={toggleSidebar}
      title={t('a11y.toggleSidebar')}
      className={cn(
        'absolute inset-y-0 z-20 hidden w-4 -translate-x-1/2 transition-all ease-linear after:absolute after:inset-y-0 after:left-1/2 after:w-0.5 hover:after:bg-sidebar-border group-data-[side=left]:-right-4 group-data-[side=right]:left-0 sm:flex',
        'in-data-[side=left]:cursor-w-resize in-data-[side=right]:cursor-e-resize',
        '[[data-side=left][data-state=collapsed]_&]:cursor-e-resize [[data-side=right][data-state=collapsed]_&]:cursor-w-resize',
        'group-data-[collapsible=offcanvas]:translate-x-0 hover:group-data-[collapsible=offcanvas]:bg-sidebar group-data-[collapsible=offcanvas]:after:left-full',
        '[[data-side=left][data-collapsible=offcanvas]_&]:-right-2',
        '[[data-side=right][data-collapsible=offcanvas]_&]:-left-2',
        className,
      )}
      {...props}
    />
  );
}

// Re-export from split modules
export {
  SidebarProvider,
  useSidebar,
} from './sidebar-context.tsx';
export {
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from './sidebar-menu.tsx';
export {
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
} from './sidebar-sections.tsx';

export { Sidebar, SidebarTrigger };
