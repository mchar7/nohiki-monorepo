import { render } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import { Progress } from './progress.tsx';

describe('Progress', () => {
  test('renders with default value', () => {
    const { container } = render(<Progress />);
    expect(container.firstChild).toBeInTheDocument();
  });

  test('renders with specified value', () => {
    const { container } = render(<Progress value={50} />);
    const indicator = container.querySelector('[data-state]');
    expect(indicator).toBeInTheDocument();
  });

  test('applies custom className', () => {
    const { container } = render(<Progress className="custom-class" />);
    expect(container.firstChild).toHaveClass('custom-class');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<Progress ref={ref} />);
    expect(ref).toHaveBeenCalled();
  });

  test('renders with 0 value', () => {
    const { container } = render(<Progress value={0} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  test('renders with 100 value', () => {
    const { container } = render(<Progress value={100} />);
    expect(container.firstChild).toBeInTheDocument();
  });
});
