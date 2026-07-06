import {
  KEYBOARD_SHORTCUTS,
  type PlatformKey,
  type ShortcutGroup,
} from '@/shared/config/keyboard-shortcuts.ts';

/** Whether the current platform is macOS (used for key badge display). */
const IS_MAC_PLATFORM: boolean =
  typeof navigator !== 'undefined' && navigator.platform.includes('Mac');

/** Unique shortcut groups present in the registry, preserving insertion order. */
const SHORTCUT_GROUPS: readonly ShortcutGroup[] = [
  ...new Set(KEYBOARD_SHORTCUTS.map((s) => s.group)),
];

/**
 * Resolves a platform-aware key label to the correct display string.
 *
 * On macOS, `Cmd/Ctrl` renders as `⌘`, `Alt/Option` as `⌥`.
 * On other platforms, `Cmd/Ctrl` renders as `Ctrl`, `Alt/Option` as `Alt`.
 */
function resolveKeyLabel(key: PlatformKey | string): string {
  if (key === 'Cmd/Ctrl') {
    return IS_MAC_PLATFORM ? '⌘' : 'Ctrl';
  }
  if (key === 'Alt/Option') {
    return IS_MAC_PLATFORM ? '⌥' : 'Alt';
  }
  if (key === 'Shift') {
    return IS_MAC_PLATFORM ? '⇧' : 'Shift';
  }
  return key;
}

export { resolveKeyLabel, SHORTCUT_GROUPS };
