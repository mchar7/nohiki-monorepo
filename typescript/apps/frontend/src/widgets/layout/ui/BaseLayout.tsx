import { Outlet } from '@tanstack/react-router';
import { type JSX, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLogout } from '@/shared/api/index.ts';
import { SHORTCUT_TRIGGER_KEY } from '@/shared/config';
import { useGlobalKeyboardShortcut } from '@/shared/lib';
import { MainScrollRefContext } from '@/shared/lib/index.ts';
import { ConnectivityIndicator } from '@/shared/ui/connectivity-indicator.tsx';
import { KeyboardShortcutsDialog } from '@/shared/ui/keyboard-shortcuts-dialog.tsx';
import { RouteProgress } from '@/shared/ui/route-progress.tsx';
import { Separator } from '@/shared/ui/separator.tsx';
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/shared/ui/sidebar.tsx';
import { SkipLink } from '@/shared/ui/skip-link.tsx';
import { AppSidebar } from './AppSidebar.tsx';
import { BottomNav } from './BottomNav.tsx';
import { CommandPalette } from './CommandPalette.tsx';
import { PageBreadcrumb } from './PageBreadcrumb.tsx';

/** Shortcut hint label for the command palette trigger button. */
const CMD_K_LABEL = '⌘K';

function openCommandPalette(): void {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }));
}

function BaseLayout({ children }: BaseLayoutProps): JSX.Element {
  const { t } = useTranslation(['common']);
  const logoutMutation = useLogout();
  const mainRef = useRef<HTMLElement>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  useGlobalKeyboardShortcut({
    key: SHORTCUT_TRIGGER_KEY,
    onActivate: () => setShortcutsOpen(true),
  });
  const handleSignOut = (): void => {
    logoutMutation.mutate();
  };

  return (
    <>
      <SkipLink />
      <RouteProgress />
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-2 h-4" />
            <PageBreadcrumb />

            {/* Right side of header */}
            <div className="ml-auto flex items-center gap-2">
              <ConnectivityIndicator />
              {/* Discoverable shortcut hint - clicking opens the command palette */}
              <button
                type="button"
                onClick={openCommandPalette}
                aria-label={t('a11y.openCommandPalette')}
                className="hidden items-center gap-1 rounded border px-1.5 py-0.5 text-muted-foreground text-xs transition-colors hover:text-foreground sm:flex"
              >
                <span>{CMD_K_LABEL}</span>
              </button>
            </div>
          </header>
          <MainScrollRefContext.Provider value={mainRef}>
            <main
              id="main-content"
              tabIndex={-1}
              ref={mainRef}
              className="flex-1 overflow-auto pb-16 focus:outline-none md:pb-0"
              style={{
                paddingLeft: 'env(safe-area-inset-left)',
                paddingRight: 'env(safe-area-inset-right)',
              }}
            >
              {children ?? <Outlet />}
            </main>
          </MainScrollRefContext.Provider>
          <BottomNav />
        </SidebarInset>
        <CommandPalette onSignOut={handleSignOut} onOpenShortcuts={() => setShortcutsOpen(true)} />
      </SidebarProvider>
      <KeyboardShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </>
  );
}

interface BaseLayoutProps {
  readonly children?: React.ReactNode;
}

export { BaseLayout };
