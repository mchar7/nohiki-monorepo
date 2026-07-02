import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, vi } from 'vitest';
import { ConfirmDialog } from './ConfirmDialog.tsx';

describe('ConfirmDialog - rendering', () => {
  test('renders dialog when open', () => {
    render(
      <ConfirmDialog
        isOpen={true}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        title="Test Title"
        message="Test message"
      />,
    );

    expect(screen.getByText('Test Title')).toBeInTheDocument();
    expect(screen.getByText('Test message')).toBeInTheDocument();
  });
});

describe('ConfirmDialog - actions', () => {
  test('calls onConfirm when confirm button is clicked', async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();

    render(
      <ConfirmDialog
        isOpen={true}
        onClose={onClose}
        onConfirm={onConfirm}
        title="Test Title"
        message="Test message"
      />,
    );

    const confirmButton = screen.getByText('Confirm');
    await userEvent.click(confirmButton);

    expect(onConfirm).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  test('calls onClose when cancel button is clicked', async () => {
    const onClose = vi.fn();

    render(
      <ConfirmDialog
        isOpen={true}
        onClose={onClose}
        onConfirm={vi.fn()}
        title="Test Title"
        message="Test message"
      />,
    );

    const cancelButton = screen.getByText('Cancel');
    await userEvent.click(cancelButton);

    expect(onClose).toHaveBeenCalled();
  });
});
