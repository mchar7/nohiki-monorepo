import { useEffect, useRef } from 'react';
import { useIsMobileLayout } from '@/shared/lib/index.ts';
import { useSidebar } from '@/shared/ui/sidebar.tsx';

interface UseResponsiveSidebarProps {
  formWidth?: number;
  isEditorPage?: boolean;
}

interface UserAction {
  action: 'open' | 'close';
  timestamp: number;
}

/** Minimum width (px) needed for the form to be comfortable */
const FORM_MIN_COMFORTABLE_WIDTH: number = 600;
/** Debounce time (ms) to prevent rapid toggling */
const DEBOUNCE_TIME: number = 300;
/** Time window (ms) to consider a user action as "recent" */
const USER_ACTION_WINDOW: number = 5000;
/** Short settle delay (ms) after a programmatic sidebar toggle */
const AUTO_COLLAPSE_SETTLE_MS: number = 100;
/** Minimum width change (px) required to trigger re-evaluation */
const WIDTH_CHANGE_THRESHOLD_PX: number = 50;

// Helper function to check if user recently performed an action
const hasUserRecentlyActed = (lastAction: UserAction | null): boolean =>
  lastAction !== null && Date.now() - lastAction.timestamp < USER_ACTION_WINDOW;

// Helper function to determine if we should auto-collapse
const shouldAutoCollapse = (
  formWidth: number,
  isOpen: boolean,
  lastUserAction: UserAction | null,
): boolean => {
  const needsCollapse = formWidth < FORM_MIN_COMFORTABLE_WIDTH && isOpen;
  if (!needsCollapse) {
    return false;
  }

  const userRecentlyActed = hasUserRecentlyActed(lastUserAction);
  return !userRecentlyActed || lastUserAction?.action === 'close';
};

// Helper function to determine if we should auto-reopen
const shouldAutoReopen = (
  formWidth: number,
  isOpen: boolean,
  wasAutoCollapsed: boolean,
  lastUserAction: UserAction | null,
): boolean => {
  const hasSpace = formWidth >= FORM_MIN_COMFORTABLE_WIDTH && !isOpen && wasAutoCollapsed;
  if (!hasSpace) {
    return false;
  }

  const userRecentlyActed = hasUserRecentlyActed(lastUserAction);
  return !userRecentlyActed || lastUserAction?.action === 'open';
};

interface SidebarRefs {
  readonly lastUserActionRef: React.RefObject<UserAction | null>;
  readonly autoCollapsedRef: React.RefObject<boolean>;
}

/** Applies sidebar toggle with a short settle delay to prevent re-triggering. */
function applySidebarToggle(
  setOpen: (isOpen: boolean) => void,
  newState: boolean,
  autoCollapsedRef: React.RefObject<boolean>,
): void {
  autoCollapsedRef.current = true;
  setOpen(newState);
  setTimeout(() => {
    autoCollapsedRef.current = false;
  }, AUTO_COLLAPSE_SETTLE_MS);
}

/** Evaluates responsive sidebar logic and applies collapse/reopen if needed. */
function evaluateResponsiveSidebar(
  formWidth: number,
  open: boolean,
  setOpen: (newState: boolean) => void,
  refs: SidebarRefs,
): void {
  const lastAction = refs.lastUserActionRef.current;

  if (shouldAutoCollapse(formWidth, open, lastAction)) {
    applySidebarToggle(setOpen, false, refs.autoCollapsedRef);
  } else if (shouldAutoReopen(formWidth, open, refs.autoCollapsedRef.current, lastAction)) {
    applySidebarToggle(setOpen, true, refs.autoCollapsedRef);
  }
}

export function useResponsiveSidebar({
  formWidth,
  isEditorPage = false,
}: UseResponsiveSidebarProps): { isMobileDevice: boolean } {
  const { setOpen, open, isMobile: sidebarIsMobile } = useSidebar();
  const isMobileDevice = useIsMobileLayout();

  const lastUserActionRef = useRef<UserAction | null>(null);
  const autoCollapsedRef = useRef(false);
  const debounceTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastFormWidthRef = useRef<number | undefined>(undefined);

  const previousOpenRef = useRef(open);
  useEffect(() => {
    if (previousOpenRef.current !== open && !autoCollapsedRef.current) {
      lastUserActionRef.current = { action: open ? 'open' : 'close', timestamp: Date.now() };
    }
    previousOpenRef.current = open;
  }, [open]);

  useEffect(() => {
    if (!isEditorPage || isMobileDevice || sidebarIsMobile) {
      return;
    }
    if (debounceTimeoutRef.current) {
      clearTimeout(debounceTimeoutRef.current);
    }
    if (formWidth === undefined) {
      return;
    }

    const lastWidth = lastFormWidthRef.current;
    if (lastWidth !== undefined && Math.abs(formWidth - lastWidth) < WIDTH_CHANGE_THRESHOLD_PX) {
      return;
    }
    lastFormWidthRef.current = formWidth;

    debounceTimeoutRef.current = setTimeout(() => {
      evaluateResponsiveSidebar(formWidth, open, setOpen, {
        lastUserActionRef,
        autoCollapsedRef,
      });
    }, DEBOUNCE_TIME);

    return (): void => {
      if (debounceTimeoutRef.current) {
        clearTimeout(debounceTimeoutRef.current);
      }
    };
  }, [formWidth, isEditorPage, isMobileDevice, sidebarIsMobile, open, setOpen]);

  useEffect(
    (): (() => void) => (): void => {
      if (debounceTimeoutRef.current) {
        clearTimeout(debounceTimeoutRef.current);
      }
    },
    [],
  );

  return { isMobileDevice: isMobileDevice || sidebarIsMobile };
}
