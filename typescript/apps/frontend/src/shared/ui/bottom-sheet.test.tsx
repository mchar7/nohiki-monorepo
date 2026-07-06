import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, vi } from 'vitest';
import { BottomSheet } from './bottom-sheet.tsx';

const mockUseSwipeToDismiss = vi.fn();

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useSwipeToDismiss: (args: unknown) => mockUseSwipeToDismiss(args),
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

const defaultProps = {
  open: true,
  onOpenChange: vi.fn(),
  title: 'Test Title',
  children: <div>Test Content</div>,
};

describe('BottomSheet', () => {
  test('opens and renders title when open={true}', () => {
    render(<BottomSheet {...defaultProps} />);
    expect(screen.getByText('Test Title')).toBeInTheDocument();
    expect(screen.getByText('Test Content')).toBeInTheDocument();
  });

  test('closes when onOpenChange(false) is called', async () => {
    const onOpenChange = vi.fn();
    render(<BottomSheet {...defaultProps} onOpenChange={onOpenChange} />);

    // Press Escape to trigger onOpenChange(false) via Radix Dialog
    await userEvent.keyboard('{Escape}');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  test('renders description when provided', () => {
    render(<BottomSheet {...defaultProps} description="Test Description" />);
    expect(screen.getByText('Test Description')).toBeInTheDocument();
  });

  test('omits aria-describedby when no description provided', () => {
    render(<BottomSheet {...defaultProps} />);
    const sheetContent = document.querySelector('[data-slot="sheet-content"]');
    expect(sheetContent).not.toHaveAttribute('aria-describedby');
  });

  test('className prop is forwarded to SheetContent', () => {
    render(<BottomSheet {...defaultProps} className="test-class" />);
    const sheetContent = document.querySelector('[data-slot="sheet-content"]');
    expect(sheetContent).toHaveClass('test-class');
  });

  test("useSwipeToDismiss is called with { ref, onDismiss, direction: 'down', enabled: open }", () => {
    render(<BottomSheet {...defaultProps} open={true} />);

    expect(mockUseSwipeToDismiss).toHaveBeenCalledWith(
      expect.objectContaining({
        direction: 'down',
        enabled: true,
      }),
    );

    // Check ref and onDismiss specifically
    const [[lastCallArg]] = mockUseSwipeToDismiss.mock.calls as [
      [Parameters<typeof mockUseSwipeToDismiss>[0]],
    ];
    expect(lastCallArg.ref).toBeDefined();
    expect(typeof lastCallArg.onDismiss).toBe('function');

    // Verify that calling onDismiss triggers onOpenChange(false)
    const onOpenChange = vi.fn();
    render(<BottomSheet {...defaultProps} onOpenChange={onOpenChange} />);

    const [newCallArg] = mockUseSwipeToDismiss.mock.lastCall as [
      Parameters<typeof mockUseSwipeToDismiss>[0],
    ];
    newCallArg.onDismiss();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
