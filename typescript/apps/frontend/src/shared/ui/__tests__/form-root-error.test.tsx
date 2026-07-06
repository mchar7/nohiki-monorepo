import { render, screen } from '@testing-library/react';
import { describe, expect } from 'vitest';
import { FormRootError } from '../form-root-error.tsx';

describe('FormRootError', () => {
  test('renders with role="alert" when error string is provided', () => {
    render(<FormRootError error="Something went wrong" />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  test('contains AlertCircle icon (svg element)', () => {
    render(<FormRootError error="Error occurred" />);

    const alert = screen.getByRole('alert');
    const svg = alert.querySelector('svg');
    expect(svg).toBeInTheDocument();
  });

  test('has text-destructive CSS class', () => {
    render(<FormRootError error="Validation failed" />);

    const alert = screen.getByRole('alert');
    expect(alert.className).toContain('text-destructive');
  });

  test('has data-testid="form-root-error" attribute', () => {
    render(<FormRootError error="Test error" />);

    expect(screen.getByTestId('form-root-error')).toBeInTheDocument();
  });

  test('displays the error message text', () => {
    const errorMessage = 'Invalid credentials. Please try again.';
    render(<FormRootError error={errorMessage} />);

    expect(screen.getByText(errorMessage)).toBeInTheDocument();
  });

  test('returns null when error is undefined', () => {
    const { container } = render(<FormRootError error={undefined} />);

    expect(container.innerHTML).toBe('');
  });

  test('returns null when error is empty string', () => {
    const { container } = render(<FormRootError error="" />);

    expect(container.innerHTML).toBe('');
  });
});
