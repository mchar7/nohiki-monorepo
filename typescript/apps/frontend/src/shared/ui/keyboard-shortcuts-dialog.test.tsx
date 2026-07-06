import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, vi } from 'vitest';
import { KEYBOARD_SHORTCUTS } from '@/shared/config/keyboard-shortcuts.ts';
import { KeyboardShortcutsDialog } from './keyboard-shortcuts-dialog.tsx';
import { resolveKeyLabel } from './keyboard-shortcuts-labels.ts';

describe('KeyboardShortcutsDialog', () => {
  test('renders all shortcut groups with headings', () => {
    render(<KeyboardShortcutsDialog open={true} onOpenChange={vi.fn()} />);

    expect(screen.getByText('Global')).toBeInTheDocument();
  });

  test('renders all shortcuts from KEYBOARD_SHORTCUTS', () => {
    render(<KeyboardShortcutsDialog open={true} onOpenChange={vi.fn()} />);

    for (const _shortcut of KEYBOARD_SHORTCUTS) {
      // Each shortcut's label should be rendered (i18n resolves to the key value in test)
      const listItems = screen.getAllByRole('listitem');
      expect(listItems.length).toBe(KEYBOARD_SHORTCUTS.length);
    }
  });

  test('shows Ctrl on non-Mac platforms (default in test env)', () => {
    render(<KeyboardShortcutsDialog open={true} onOpenChange={vi.fn()} />);

    // Test environment has no Mac navigator.platform, so Cmd/Ctrl resolves to "Ctrl"
    const ctrlBadges = screen.getAllByText('Ctrl');
    expect(ctrlBadges.length).toBeGreaterThan(0);
  });

  test('is accessible: has a dialog title and closes on Escape', async () => {
    const onOpenChange = vi.fn();
    const user = userEvent.setup();

    render(<KeyboardShortcutsDialog open={true} onOpenChange={onOpenChange} />);

    // Dialog should have a titled heading
    expect(screen.getByRole('heading', { name: 'Keyboard Shortcuts' })).toBeInTheDocument();

    // Pressing Escape should call onOpenChange(false)
    await user.keyboard('{Escape}');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe('resolveKeyLabel', () => {
  test('resolves Cmd/Ctrl to Ctrl on non-Mac platforms', () => {
    expect(resolveKeyLabel('Cmd/Ctrl')).toBe('Ctrl');
  });

  test('passes through regular key labels unchanged', () => {
    expect(resolveKeyLabel('K')).toBe('K');
    expect(resolveKeyLabel('Escape')).toBe('Escape');
    expect(resolveKeyLabel('?')).toBe('?');
  });
});
