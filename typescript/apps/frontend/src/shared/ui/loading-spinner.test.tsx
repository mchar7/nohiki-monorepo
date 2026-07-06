import { render, screen } from '@testing-library/react';
import { describe, expect } from 'vitest';
import { LoadingSpinner } from './loading-spinner.tsx';

describe('LoadingSpinner', () => {
  test('renders spinner without text', () => {
    const { container } = render(<LoadingSpinner />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  test('renders with text', () => {
    render(<LoadingSpinner text="Loading..." />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  test('renders with description', () => {
    render(<LoadingSpinner text="Loading" description="Please wait" />);
    expect(screen.getByText('Please wait')).toBeInTheDocument();
  });

  test('renders with different sizes', () => {
    const { rerender, container } = render(<LoadingSpinner size="sm" />);
    expect(container.querySelector('svg')).toBeInTheDocument();

    rerender(<LoadingSpinner size="md" />);
    expect(container.querySelector('svg')).toBeInTheDocument();

    rerender(<LoadingSpinner size="lg" />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  test('renders inline variant', () => {
    render(<LoadingSpinner variant="inline" text="Loading" />);
    expect(screen.getByText('Loading')).toBeInTheDocument();
  });

  test('renders overlay variant', () => {
    const { container } = render(<LoadingSpinner variant="overlay" />);
    expect(container.firstChild).toHaveClass('absolute');
  });

  test('renders centered by default', () => {
    const { container } = render(<LoadingSpinner />);
    expect(container.firstChild).toHaveClass('flex', 'items-center', 'justify-center');
  });

  test('renders non-centered when centered=false', () => {
    const { container } = render(<LoadingSpinner centered={false} />);
    expect(container.firstChild).not.toHaveClass('items-center');
  });

  test('applies custom className', () => {
    const { container } = render(<LoadingSpinner className="custom-class" />);
    expect(container.firstChild).toHaveClass('custom-class');
  });
});
