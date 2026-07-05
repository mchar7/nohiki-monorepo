import { useEffect } from 'react';

interface UseGlobalKeyboardShortcutOptions {
  /** The key to listen for (e.g. '?', 'k'). Matched against `event.key`. */
  readonly key: string;
  /** Modifier keys required (default: none). */
  readonly modifiers?: {
    readonly meta?: boolean;
    readonly ctrl?: boolean;
    readonly shift?: boolean;
    readonly alt?: boolean;
  };
  /** Callback invoked when the shortcut fires. */
  readonly onActivate: () => void;
  /** Whether the shortcut is currently active (default: true).
   *  Use to disable shortcuts when a modal is open, etc. */
  readonly enabled?: boolean;
}

/**
 * Checks whether the event target is an interactive text input element.
 *
 * Prevents keyboard shortcuts from firing while the user types in form fields,
 * textareas, or contenteditable regions.
 */
function isInputTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target.getAttribute('contenteditable') === 'true'
  );
}

/**
 * Checks whether all required modifier keys are pressed.
 *
 * Returns `true` when every modifier marked `true` in the options
 * is also held during the keyboard event. Unspecified modifiers are ignored.
 */
function modifiersMatch(
  event: KeyboardEvent,
  modifiers: UseGlobalKeyboardShortcutOptions['modifiers'],
): boolean {
  if (!modifiers) {
    return true;
  }
  if (modifiers.meta && !event.metaKey) {
    return false;
  }
  if (modifiers.ctrl && !event.ctrlKey) {
    return false;
  }
  if (modifiers.shift && !event.shiftKey) {
    return false;
  }
  if (modifiers.alt && !event.altKey) {
    return false;
  }
  return true;
}

/**
 * Registers a global keyboard shortcut with an input-element guard.
 *
 * The shortcut will NOT fire when the user is focused on an `<input>`,
 * `<textarea>`, or `contenteditable` element. This prevents accidental
 * activation while typing in form fields.
 *
 * @example
 * ```tsx
 * useGlobalKeyboardShortcut({
 *   key: '?',
 *   onActivate: () => setShortcutsOpen(true),
 * });
 * ```
 */
function useGlobalKeyboardShortcut({
  key,
  modifiers,
  onActivate,
  enabled = true,
}: UseGlobalKeyboardShortcutOptions): void {
  useEffect(() => {
    if (!enabled) {
      return;
    }

    const handler = (event: KeyboardEvent): void => {
      if (event.key !== key) {
        return;
      }
      if (!modifiersMatch(event, modifiers)) {
        return;
      }
      if (isInputTarget(event.target)) {
        return;
      }

      event.preventDefault();
      onActivate();
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [key, modifiers, onActivate, enabled]);
}

export { useGlobalKeyboardShortcut };
