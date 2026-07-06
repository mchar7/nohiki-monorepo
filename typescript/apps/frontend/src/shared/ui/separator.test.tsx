import { render } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import { Separator } from './separator.tsx';

describe('Separator', () => {
  test('renders horizontal separator by default', () => {
    const { container } = render(<Separator />);
    const separator = container.firstChild as HTMLElement;
    expect(separator).toBeInTheDocument();
    expect(separator).toHaveClass('h-px', 'w-full');
  });

  test('renders vertical separator', () => {
    const { container } = render(<Separator orientation="vertical" />);
    const separator = container.firstChild as HTMLElement;
    expect(separator).toHaveClass('h-full', 'w-px');
  });

  test('applies custom className', () => {
    const { container } = render(<Separator className="custom-class" />);
    const separator = container.firstChild as HTMLElement;
    expect(separator).toHaveClass('custom-class');
  });

  test('is decorative by default', () => {
    const { container } = render(<Separator />);
    const separator = container.firstChild as HTMLElement;
    expect(separator).toHaveAttribute('data-orientation', 'horizontal');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<Separator ref={ref} />);
    expect(ref).toHaveBeenCalled();
  });
});
