import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useSwipeToDismiss } from '@/shared/lib/index.ts';
import { PreviewSheet } from './PreviewSheet.tsx';

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useSwipeToDismiss: vi.fn(),
  };
});

vi.mock('./DynamicPreview.tsx', () => ({
  DynamicPreview: vi.fn(() => <div data-testid="dynamic-preview" />),
}));

describe('PreviewSheet', () => {
  const defaultProps: Parameters<typeof PreviewSheet>[0] = {
    open: true,
    onOpenChange: vi.fn<(open: boolean) => void>(),
    pageSize: { width: 210, height: 297, unit: 'mm' },
    templateVersionId: 'v1',
    templateData: { sections: [] },
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders content when open is true', () => {
    render(<PreviewSheet {...defaultProps} />);
    expect(screen.getByTestId('dynamic-preview')).toBeInTheDocument();
  });

  test('calls useSwipeToDismiss with correct parameters', () => {
    render(<PreviewSheet {...defaultProps} />);
    expect(useSwipeToDismiss).toHaveBeenCalledWith(
      expect.objectContaining({
        direction: 'down',
        enabled: true,
      }),
    );
  });

  test('calls useSwipeToDismiss with enabled=false when closed', () => {
    render(<PreviewSheet {...defaultProps} open={false} />);
    expect(useSwipeToDismiss).toHaveBeenCalledWith(
      expect.objectContaining({
        direction: 'down',
        enabled: false,
      }),
    );
  });

  test('triggers onOpenChange(false) when close button is clicked', () => {
    render(<PreviewSheet {...defaultProps} />);
    const closeButton = screen.getByRole('button');
    fireEvent.click(closeButton);
    expect(defaultProps.onOpenChange).toHaveBeenCalledWith(false);
  });
});
