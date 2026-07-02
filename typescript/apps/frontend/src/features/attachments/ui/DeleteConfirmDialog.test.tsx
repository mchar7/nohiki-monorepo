import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, vi } from 'vitest';
import { DeleteConfirmDialog } from './DeleteConfirmDialog.tsx';

let mockIsMobile = false;

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: () => mockIsMobile,
  };
});

describe('DeleteConfirmDialog rendering', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    filename: 'test-resume.pdf',
    onConfirm: vi.fn(),
    isDeleting: false,
  };

  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('renders AlertDialog on desktop with title, description, and buttons', () => {
    mockIsMobile = false;
    render(<DeleteConfirmDialog {...defaultProps} />);
    expect(screen.getByText('Delete Attachment')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Are you sure you want to delete "test-resume.pdf"? This action cannot be undone.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(document.querySelector('[data-slot="sheet-content"]')).not.toBeInTheDocument();
  });

  test('renders BottomSheet on mobile with stacked buttons', () => {
    mockIsMobile = true;
    render(<DeleteConfirmDialog {...defaultProps} />);
    expect(screen.getByText('Delete Attachment')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Are you sure you want to delete "test-resume.pdf"? This action cannot be undone.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });
});

describe('DeleteConfirmDialog interactions', () => {
  const defaultProps = {
    open: true,
    onOpenChange: vi.fn(),
    filename: 'test-resume.pdf',
    onConfirm: vi.fn(),
    isDeleting: false,
  };

  afterEach(() => {
    vi.clearAllMocks();
    mockIsMobile = false;
  });

  test('calls onConfirm when confirm button is clicked', async () => {
    render(<DeleteConfirmDialog {...defaultProps} />);
    const confirmBtn = screen.getByRole('button', { name: 'Delete' });
    await userEvent.click(confirmBtn);
    expect(defaultProps.onConfirm).toHaveBeenCalledOnce();
  });

  test('calls onOpenChange(false) when cancel button is clicked', async () => {
    render(<DeleteConfirmDialog {...defaultProps} />);
    const cancelBtn = screen.getByRole('button', { name: 'Cancel' });
    await userEvent.click(cancelBtn);
    expect(defaultProps.onOpenChange).toHaveBeenCalledWith(false);
  });

  test('disables buttons and shows processing text when isDeleting is true', () => {
    render(<DeleteConfirmDialog {...defaultProps} isDeleting={true} />);
    const confirmBtn = screen.getByRole('button', { name: 'Processing...' });
    expect(confirmBtn).toBeDisabled();
    const cancelBtn = screen.getByRole('button', { name: 'Cancel' });
    expect(cancelBtn).toBeDisabled();
  });
});
