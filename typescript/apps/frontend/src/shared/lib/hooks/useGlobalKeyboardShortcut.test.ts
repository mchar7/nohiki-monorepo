import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, vi } from 'vitest';
import { useGlobalKeyboardShortcut } from './useGlobalKeyboardShortcut.ts';

/** Dispatches a keydown event on `document` with the given properties. */
function fireKeyDown(options: KeyboardEventInit): void {
  document.dispatchEvent(new KeyboardEvent('keydown', { ...options, bubbles: true }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useGlobalKeyboardShortcut - key matching', () => {
  test('calls onActivate when the matching key is pressed', () => {
    const onActivate = vi.fn();
    renderHook(() => useGlobalKeyboardShortcut({ key: '?', onActivate }));

    fireKeyDown({ key: '?' });

    expect(onActivate).toHaveBeenCalledOnce();
  });

  test('does NOT call onActivate when a different key is pressed', () => {
    const onActivate = vi.fn();
    renderHook(() => useGlobalKeyboardShortcut({ key: '?', onActivate }));

    fireKeyDown({ key: 'a' });

    expect(onActivate).not.toHaveBeenCalled();
  });

  test('checks modifier keys (meta, ctrl, shift, alt)', () => {
    const onActivate = vi.fn();
    renderHook(() =>
      useGlobalKeyboardShortcut({
        key: 'k',
        modifiers: { meta: true },
        onActivate,
      }),
    );

    // Without meta: should not fire
    fireKeyDown({ key: 'k' });
    expect(onActivate).not.toHaveBeenCalled();

    // With meta: should fire
    fireKeyDown({ key: 'k', metaKey: true });
    expect(onActivate).toHaveBeenCalledOnce();
  });
});

describe('useGlobalKeyboardShortcut - focus guards', () => {
  test('does NOT fire when focused on an <input> element', () => {
    const onActivate = vi.fn();
    renderHook(() => useGlobalKeyboardShortcut({ key: '?', onActivate }));

    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    input.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));

    expect(onActivate).not.toHaveBeenCalled();
    document.body.removeChild(input);
  });

  test('does NOT fire when focused on a <textarea> element', () => {
    const onActivate = vi.fn();
    renderHook(() => useGlobalKeyboardShortcut({ key: '?', onActivate }));

    const textarea = document.createElement('textarea');
    document.body.appendChild(textarea);
    textarea.focus();

    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));

    expect(onActivate).not.toHaveBeenCalled();
    document.body.removeChild(textarea);
  });

  test('does NOT fire when focused on a contenteditable element', () => {
    const onActivate = vi.fn();
    renderHook(() => useGlobalKeyboardShortcut({ key: '?', onActivate }));

    const div = document.createElement('div');
    div.setAttribute('contenteditable', 'true');
    document.body.appendChild(div);
    div.focus();

    div.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));

    expect(onActivate).not.toHaveBeenCalled();
    document.body.removeChild(div);
  });
});

describe('useGlobalKeyboardShortcut - control', () => {
  test('does NOT fire when enabled is false', () => {
    const onActivate = vi.fn();
    renderHook(() => useGlobalKeyboardShortcut({ key: '?', onActivate, enabled: false }));

    fireKeyDown({ key: '?' });

    expect(onActivate).not.toHaveBeenCalled();
  });

  test('cleans up the event listener on unmount', () => {
    const onActivate = vi.fn();
    const { unmount } = renderHook(() => useGlobalKeyboardShortcut({ key: '?', onActivate }));

    unmount();

    fireKeyDown({ key: '?' });

    expect(onActivate).not.toHaveBeenCalled();
  });
});
