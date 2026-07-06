import { Slot } from '@radix-ui/react-slot';
import { type JSX, useRef } from 'react';
import { useIsMobileLayout } from '@/shared/lib/index.ts';
import { BottomSheet } from './bottom-sheet.tsx';
import { Button } from './button.tsx';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './dropdown-menu.tsx';
import type { ResponsiveMenuItemProps, ResponsiveMenuProps } from './responsive-menu.types.ts';
import { ResponsiveMenuContext } from './responsive-menu-context.ts';
import { useResponsiveMenuContext } from './responsive-menu-hooks.ts';
import { Separator } from './separator.tsx';

/** Renders DropdownMenu on desktop and BottomSheet on mobile.
 *  Use ResponsiveMenuItem and ResponsiveMenuSeparator as children. */
function ResponsiveMenu({
  open,
  onOpenChange,
  title,
  trigger,
  children,
  align = 'end',
}: ResponsiveMenuProps): JSX.Element {
  const isMobile = useIsMobileLayout();
  // When an item opens a Dialog, the DropdownMenu's onCloseAutoFocus races
  // the Dialog's focus-trap, causing intermittent focus conflicts. Tracking
  // item-initiated closes lets us suppress auto-focus so the next overlay
  // (Dialog, AlertDialog) owns focus cleanly.
  const closedByItemRef = useRef(false);

  const close = (): void => {
    closedByItemRef.current = true;
    onOpenChange(false);
  };

  const handleOpenChange = (nextOpen: boolean): void => {
    if (nextOpen) {
      closedByItemRef.current = false;
    }
    onOpenChange(nextOpen);
  };

  const handleCloseAutoFocus = (e: Event): void => {
    if (closedByItemRef.current) {
      e.preventDefault();
      closedByItemRef.current = false;
    }
  };

  if (isMobile) {
    return (
      <ResponsiveMenuContext.Provider value={{ isMobile: true, close }}>
        <Slot onClick={() => onOpenChange(true)}>{trigger}</Slot>
        <BottomSheet open={open} onOpenChange={onOpenChange} title={title}>
          <div className="flex flex-col gap-1 py-2">{children}</div>
        </BottomSheet>
      </ResponsiveMenuContext.Provider>
    );
  }

  return (
    <ResponsiveMenuContext.Provider value={{ isMobile: false, close }}>
      <DropdownMenu open={open} onOpenChange={handleOpenChange}>
        <DropdownMenuTrigger asChild={true}>{trigger}</DropdownMenuTrigger>
        <DropdownMenuContent align={align} onCloseAutoFocus={handleCloseAutoFocus}>
          {children}
        </DropdownMenuContent>
      </DropdownMenu>
    </ResponsiveMenuContext.Provider>
  );
}

/** A menu item that renders as DropdownMenuItem on desktop and a full-width Button on mobile. */
function ResponsiveMenuItem({
  icon,
  children,
  variant = 'default',
  disabled = false,
  onClick,
  className,
}: ResponsiveMenuItemProps): JSX.Element {
  const { isMobile, close } = useResponsiveMenuContext();

  const handleClick = (): void => {
    onClick();
    close();
  };

  if (isMobile) {
    const colorClass = variant === 'destructive' ? ' text-destructive' : '';
    return (
      <Button
        variant="ghost"
        className={`w-full justify-start gap-2${colorClass}${className ? ` ${className}` : ''}`}
        disabled={disabled}
        onClick={handleClick}
      >
        {icon}
        {children}
      </Button>
    );
  }

  const destructiveClass =
    variant === 'destructive' ? 'text-destructive focus:text-destructive' : '';
  return (
    <DropdownMenuItem
      disabled={disabled}
      onClick={handleClick}
      className={`flex items-center gap-2 ${destructiveClass}${className ? ` ${className}` : ''}`.trim()}
    >
      {icon}
      {children}
    </DropdownMenuItem>
  );
}

/** A separator that renders as DropdownMenuSeparator on desktop and Separator on mobile. */
function ResponsiveMenuSeparator(): JSX.Element {
  const { isMobile } = useResponsiveMenuContext();

  if (isMobile) {
    return <Separator className="my-1" />;
  }

  return <DropdownMenuSeparator />;
}

export { ResponsiveMenu, ResponsiveMenuItem, ResponsiveMenuSeparator };
