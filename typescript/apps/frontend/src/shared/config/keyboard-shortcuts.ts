/** Platform-aware key label (e.g. Cmd on Mac, Ctrl on Windows). */
type PlatformKey = 'Cmd/Ctrl' | 'Shift' | 'Alt/Option';

/** Grouping category for the shortcuts dialog. */
type ShortcutGroup = 'global' | 'navigation' | 'editor';

/**
 * A keyboard shortcut definition for display purposes.
 *
 * This is a data-only registry; it does NOT register event listeners.
 * Actual listeners remain in their respective components.
 */
interface ShortcutDefinition {
  /** Ordered key combination, e.g. ['Cmd/Ctrl', 'K']. */
  readonly keys: readonly (PlatformKey | string)[];
  /** i18n key for the action description. */
  readonly labelKey: string;
  /** Grouping for the shortcuts dialog. */
  readonly group: ShortcutGroup;
}

/** Trigger key for opening the keyboard shortcuts dialog. */
const SHORTCUT_TRIGGER_KEY = '?';

/** All registered keyboard shortcuts. Typed as const for exhaustive rendering. */
const KEYBOARD_SHORTCUTS: readonly ShortcutDefinition[] = [
  { keys: ['Cmd/Ctrl', 'K'], labelKey: 'common:shortcuts.openPalette', group: 'global' },
  { keys: ['Cmd/Ctrl', 'B'], labelKey: 'common:shortcuts.toggleSidebar', group: 'global' },
  { keys: ['?'], labelKey: 'common:shortcuts.openShortcutsGuide', group: 'global' },
  { keys: ['Escape'], labelKey: 'common:shortcuts.closeDialog', group: 'global' },
] as const;

export type { PlatformKey, ShortcutGroup };
export { KEYBOARD_SHORTCUTS, SHORTCUT_TRIGGER_KEY };
