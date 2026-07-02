/**
 * Global command palette triggered by Cmd+K / Ctrl+K.
 *
 * Flattens all navigation items from MAIN_NAVIGATION (including nested children)
 * into a searchable list. Also exposes quick actions for theme toggling and
 * sign-out. When the user types 2+ characters, switches to global search mode
 * querying listings and skills in parallel.
 */

import { useNavigate } from '@tanstack/react-router';
import { Keyboard, LogOut, Moon, Sun } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MAIN_NAVIGATION, type NavItem } from '@/shared/config/index.ts';
import { handleNavigationPromise, useTheme } from '@/shared/lib/index.ts';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/shared/ui/command.tsx';
import { Dialog, DialogContent, DialogTitle } from '@/shared/ui/dialog.tsx';
import { SEARCH_MIN_QUERY_LENGTH } from '../lib/constants.ts';
import { SearchResults } from './SearchResults.tsx';

interface FlatNavEntry {
  readonly titleKey: NavItem['titleKey'];
  readonly href: string;
  readonly icon: NavItem['icon'];
}

/** Recursively flattens nav items, only including entries that have a concrete href. */
function flattenNavItems(items: readonly NavItem[]): FlatNavEntry[] {
  const result: FlatNavEntry[] = [];

  for (const item of items) {
    if (item.href) {
      result.push({ titleKey: item.titleKey, href: item.href, icon: item.icon });
    }
    if (item.children) {
      result.push(...flattenNavItems(item.children));
    }
  }

  return result;
}

const MAIN_ENTRIES: FlatNavEntry[] = flattenNavItems(MAIN_NAVIGATION);

/** Registers a global Cmd+K / Ctrl+K keyboard shortcut to toggle the palette open/closed. */
function useCommandPaletteShortcut(setOpen: (updater: (prev: boolean) => boolean) => void): void {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent): void => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [setOpen]);
}

function NavGroups({ onNavigate }: { readonly onNavigate: (href: string) => void }): JSX.Element {
  const { t } = useTranslation('navigation');
  const { t: tCommon } = useTranslation('common');

  return (
    <CommandGroup heading={tCommon('modules.platform.title')}>
      {MAIN_ENTRIES.map((entry) => (
        <CommandItem
          key={entry.href}
          value={t(entry.titleKey as 'sidebar.dashboard')}
          onSelect={() => onNavigate(entry.href)}
        >
          <entry.icon />
          <span>{t(entry.titleKey as 'sidebar.dashboard')}</span>
        </CommandItem>
      ))}
    </CommandGroup>
  );
}

function QuickActionsGroup({
  onToggleTheme,
  onSignOut,
  onOpenShortcuts,
}: {
  readonly onToggleTheme: () => void;
  readonly onSignOut: () => void;
  readonly onOpenShortcuts: () => void;
}): JSX.Element {
  const { resolvedTheme } = useTheme();
  const { t: tCommon } = useTranslation('common');
  const isDark = resolvedTheme === 'dark';
  const themeKey = isDark ? 'commandPalette.switchToLight' : 'commandPalette.switchToDark';

  return (
    <CommandGroup heading={tCommon('commandPalette.quickActions')}>
      <CommandItem value={tCommon(themeKey)} onSelect={onToggleTheme}>
        {isDark ? <Sun /> : <Moon />}
        <span>{tCommon(themeKey)}</span>
      </CommandItem>

      <CommandItem value={tCommon('commandPalette.keyboardShortcuts')} onSelect={onOpenShortcuts}>
        <Keyboard />
        <span>{tCommon('commandPalette.keyboardShortcuts')}</span>
      </CommandItem>

      <CommandItem
        value={tCommon('commandPalette.signOut')}
        onSelect={onSignOut}
        className="text-destructive data-[selected=true]:text-destructive"
      >
        <LogOut />
        <span>{tCommon('commandPalette.signOut')}</span>
      </CommandItem>
    </CommandGroup>
  );
}

interface CommandPaletteProps {
  /** Callback invoked when the user selects the sign-out action. */
  readonly onSignOut: () => void;
  /** Callback invoked when the user selects the keyboard shortcuts action. */
  readonly onOpenShortcuts: () => void;
}

export function CommandPalette({ onSignOut, onOpenShortcuts }: CommandPaletteProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const navigate = useNavigate();
  const { t: tCommon } = useTranslation('common');
  const { resolvedTheme, setTheme } = useTheme();
  const isSearchMode: boolean = inputValue.length >= SEARCH_MIN_QUERY_LENGTH;

  useCommandPaletteShortcut(setOpen);

  const handleOpenChange = (nextOpen: boolean): void => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setInputValue('');
    }
  };

  const handleNavigate = (href: string): void => {
    handleOpenChange(false);
    handleNavigationPromise(navigate({ to: href }));
  };

  const handleToggleTheme = (): void => {
    handleOpenChange(false);
    setTheme(resolvedTheme === 'dark' ? 'light' : 'dark');
  };

  const handleSignOut = (): void => {
    handleOpenChange(false);
    onSignOut();
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="overflow-hidden p-0" aria-describedby={undefined}>
        <DialogTitle className="sr-only">{tCommon('commandPalette.title')}</DialogTitle>
        <Command
          shouldFilter={!isSearchMode}
          className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-group]]:px-2 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:h-5 [&_[cmdk-item]_svg]:w-5"
        >
          <CommandInput
            placeholder={tCommon('commandPalette.placeholder')}
            value={inputValue}
            onValueChange={setInputValue}
          />
          <CommandList>
            {isSearchMode ? (
              <SearchResults query={inputValue} onSelect={handleNavigate} />
            ) : (
              <>
                <CommandEmpty>{tCommon('commandPalette.noResults')}</CommandEmpty>
                <NavGroups onNavigate={handleNavigate} />
                <CommandSeparator />
                <QuickActionsGroup
                  onToggleTheme={handleToggleTheme}
                  onSignOut={handleSignOut}
                  onOpenShortcuts={() => {
                    handleOpenChange(false);
                    onOpenShortcuts();
                  }}
                />
              </>
            )}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
