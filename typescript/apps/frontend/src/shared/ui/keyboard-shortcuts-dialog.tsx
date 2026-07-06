import { cn } from '@shared/lib/index.ts';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { KEYBOARD_SHORTCUTS } from '@/shared/config/keyboard-shortcuts.ts';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './dialog.tsx';
import type { KeyboardShortcutsDialogProps } from './keyboard-shortcuts-dialog.types.ts';
import { resolveKeyLabel, SHORTCUT_GROUPS } from './keyboard-shortcuts-labels.ts';

/**
 * Modal dialog displaying all registered keyboard shortcuts grouped by category.
 *
 * Key badges adapt to the user's platform (⌘ on Mac, Ctrl on Windows/Linux).
 * Uses the Radix Dialog primitive for focus trap and Escape-to-close behavior.
 */
function KeyboardShortcutsDialog({
  open,
  onOpenChange,
}: KeyboardShortcutsDialogProps): JSX.Element {
  const { t } = useTranslation('common');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('shortcuts.title')}</DialogTitle>
          <DialogDescription className="sr-only">{t('shortcuts.title')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {SHORTCUT_GROUPS.map((group) => {
            const groupShortcuts = KEYBOARD_SHORTCUTS.filter((s) => s.group === group);

            return (
              <section key={group} aria-labelledby={`shortcuts-group-${group}`}>
                <h3
                  id={`shortcuts-group-${group}`}
                  className="mb-2 font-medium text-muted-foreground text-sm"
                >
                  {t(`shortcuts.groups.${group}`)}
                </h3>
                <ul className="space-y-1">
                  {groupShortcuts.map((shortcut) => (
                    <li
                      key={shortcut.labelKey}
                      className="flex items-center justify-between rounded-md px-2 py-1.5"
                    >
                      <span className="text-sm">{t(shortcut.labelKey)}</span>
                      <span className="flex items-center gap-1">
                        {shortcut.keys.map((key, index) => (
                          <kbd
                            key={`${shortcut.labelKey}-${String(index)}`}
                            className={cn(
                              'inline-flex h-6 min-w-6 items-center justify-center rounded border',
                              'bg-muted px-1.5 font-mono text-muted-foreground text-xs',
                            )}
                          >
                            {resolveKeyLabel(key)}
                          </kbd>
                        ))}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export { KeyboardShortcutsDialog };
