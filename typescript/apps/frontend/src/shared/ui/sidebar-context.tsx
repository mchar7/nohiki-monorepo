import { cn, useIsMobileLayout } from '@shared/lib/index.ts';
import type { CSSProperties, JSX } from 'react';
import { createContext, useContext, useEffect, useState } from 'react';
import { TooltipProvider } from './tooltip.tsx';

const SIDEBAR_COOKIE_NAME = 'sidebar:state';
const SECONDS_PER_MINUTE: number = 60;
const MINUTES_PER_HOUR: number = 60;
const HOURS_PER_DAY: number = 24;
const DAYS_PER_WEEK: number = 7;
/** Cookie max-age for sidebar state (1 week in seconds) */
const SIDEBAR_COOKIE_MAX_AGE: number =
  SECONDS_PER_MINUTE * MINUTES_PER_HOUR * HOURS_PER_DAY * DAYS_PER_WEEK;
const SIDEBAR_WIDTH = '16rem';
const SIDEBAR_WIDTH_ICON = '3rem';
const SIDEBAR_KEYBOARD_SHORTCUT = 'b';

const setSidebarCookie = (openState: boolean): void => {
  try {
    // NOTE: Consider Cookie Store API in future when:
    // 1. Development moves to HTTPS (API requires secure context)
    // 2. Browser support stabilizes (only available in very recent versions - Safari 18.4+, Firefox 140+)
    const cookieValue = `${SIDEBAR_COOKIE_NAME}=${openState}; path=/; max-age=${SIDEBAR_COOKIE_MAX_AGE}; SameSite=Lax`;
    // biome-ignore lint/suspicious/noDocumentCookie: Cookie Store API not viable for HTTP development
    document.cookie = cookieValue;
  } catch {
    // Cookie write failure is non-critical
  }
};

interface SidebarContextProps {
  state: 'expanded' | 'collapsed';
  open: boolean;
  setOpen: (open: boolean) => void;
  openMobile: boolean;
  setOpenMobile: (open: boolean) => void;
  isMobile: boolean;
  toggleSidebar: () => void;
}

const SidebarContext: React.Context<SidebarContextProps | null> =
  createContext<SidebarContextProps | null>(null);

function useSidebar(): SidebarContextProps {
  const context = useContext(SidebarContext);
  if (!context) {
    throw new Error('useSidebar must be used within a SidebarProvider.');
  }

  return context;
}

function useOpenState(
  defaultOpen: boolean,
  openProp: boolean | undefined,
  setOpenProp: ((open: boolean) => void) | undefined,
): { open: boolean; setOpen: (updater: boolean | ((prev: boolean) => boolean)) => void } {
  const [_open, _setOpen] = useState(defaultOpen);
  const open = openProp ?? _open;

  const setOpen = (updater: boolean | ((prev: boolean) => boolean)): void => {
    const openState = typeof updater === 'function' ? updater(open) : updater;
    if (setOpenProp) {
      setOpenProp(openState);
    } else {
      _setOpen(openState);
    }
    setSidebarCookie(openState);
  };

  return { open, setOpen };
}

function SidebarProvider({
  defaultOpen = true,
  open: openProp,
  onOpenChange: setOpenProp,
  className,
  style,
  children,
  ...props
}: React.ComponentProps<'div'> & {
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}): JSX.Element {
  const isMobile = useIsMobileLayout();
  const [openMobile, setOpenMobile] = useState(false);
  const { open, setOpen } = useOpenState(defaultOpen, openProp, setOpenProp);

  const toggleSidebar = (): void => {
    if (isMobile) {
      setOpenMobile((prev) => !prev);
    } else {
      setOpen((prev) => !prev);
    }
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === SIDEBAR_KEYBOARD_SHORTCUT && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        toggleSidebar();
      }
    };

    globalThis.addEventListener('keydown', handleKeyDown);
    return () => globalThis.removeEventListener('keydown', handleKeyDown);
    // biome-ignore lint/correctness/useExhaustiveDependencies: React Compiler auto-memoizes toggleSidebar
  }, [toggleSidebar]);

  const state = open ? 'expanded' : 'collapsed';

  const contextValue: SidebarContextProps = {
    state,
    open,
    setOpen,
    isMobile,
    openMobile,
    setOpenMobile,
    toggleSidebar,
  };

  return (
    <SidebarContext.Provider value={contextValue}>
      <TooltipProvider delayDuration={0}>
        <div
          data-slot="sidebar-wrapper"
          style={
            {
              '--sidebar-width': SIDEBAR_WIDTH,
              '--sidebar-width-icon': SIDEBAR_WIDTH_ICON,
              ...style,
            } as CSSProperties
          }
          className={cn(
            'group/sidebar-wrapper flex min-h-svh w-full has-data-[variant=inset]:bg-sidebar',
            className,
          )}
          {...props}
        >
          {children}
        </div>
      </TooltipProvider>
    </SidebarContext.Provider>
  );
}

/** Sidebar width used for the mobile sheet variant - capped at 85vw so it never overflows on very narrow phones */
const SIDEBAR_WIDTH_MOBILE = 'min(18rem, 85vw)';

export { SIDEBAR_WIDTH_MOBILE, SidebarProvider, useSidebar };
