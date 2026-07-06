import { render } from '@testing-library/react';
import { describe, expect } from 'vitest';
import { Skeleton } from './skeleton.tsx';

describe('Skeleton', () => {
  test('renders with default styles', () => {
    const { container } = render(<Skeleton />);
    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toBeInTheDocument();
    expect(skeleton).toHaveAttribute('data-slot', 'skeleton');
  });

  test('applies custom className', () => {
    const { container } = render(<Skeleton className="custom-class" />);
    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toHaveClass('custom-class');
  });

  test('has animation class', () => {
    const { container } = render(<Skeleton />);
    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toHaveClass('animate-pulse');
  });

  test('passes through additional props', () => {
    const { container } = render(<Skeleton data-testid="test-skeleton" />);
    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toHaveAttribute('data-testid', 'test-skeleton');
  });

  test('renders with custom dimensions', () => {
    const { container } = render(<Skeleton className="h-4 w-24" />);
    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toHaveClass('h-4', 'w-24');
  });
});
