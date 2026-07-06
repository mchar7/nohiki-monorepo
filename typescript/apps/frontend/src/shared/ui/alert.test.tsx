import { render, screen } from '@testing-library/react';
import { AlertCircle } from 'lucide-react';
import { describe, expect } from 'vitest';
import { Alert, AlertDescription, AlertTitle } from './alert.tsx';

describe('Alert', () => {
  test('renders with default variant', () => {
    render(<Alert>Alert content</Alert>);
    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveAttribute('data-slot', 'alert');
  });

  test('renders with destructive variant', () => {
    render(<Alert variant="destructive">Error message</Alert>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  test('renders with warning variant', () => {
    render(<Alert variant="warning">Warning message</Alert>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  test('renders with success variant', () => {
    render(<Alert variant="success">Success message</Alert>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  test('renders with info variant', () => {
    render(<Alert variant="info">Info message</Alert>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    render(<Alert className="custom-class">Content</Alert>);
    expect(screen.getByRole('alert')).toHaveClass('custom-class');
  });

  test('renders with icon', () => {
    render(
      <Alert>
        <AlertCircle />
        <AlertTitle>Title</AlertTitle>
      </Alert>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});

describe('AlertTitle', () => {
  test('renders children', () => {
    render(<AlertTitle>Alert Title</AlertTitle>);
    expect(screen.getByText('Alert Title')).toBeInTheDocument();
  });

  test('has correct data-slot attribute', () => {
    render(<AlertTitle>Title</AlertTitle>);
    const title = screen.getByText('Title');
    expect(title).toHaveAttribute('data-slot', 'alert-title');
  });

  test('applies custom className', () => {
    render(<AlertTitle className="custom-class">Title</AlertTitle>);
    expect(screen.getByText('Title')).toHaveClass('custom-class');
  });
});

describe('AlertDescription', () => {
  test('renders children', () => {
    render(<AlertDescription>Description text</AlertDescription>);
    expect(screen.getByText('Description text')).toBeInTheDocument();
  });

  test('has correct data-slot attribute', () => {
    render(<AlertDescription>Description</AlertDescription>);
    const description = screen.getByText('Description');
    expect(description).toHaveAttribute('data-slot', 'alert-description');
  });

  test('applies custom className', () => {
    render(<AlertDescription className="custom-class">Description</AlertDescription>);
    expect(screen.getByText('Description')).toHaveClass('custom-class');
  });
});

describe('Alert composition', () => {
  test('renders full alert with all components', () => {
    render(
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>Error</AlertTitle>
        <AlertDescription>Something went wrong.</AlertDescription>
      </Alert>,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Error')).toBeInTheDocument();
    expect(screen.getByText('Something went wrong.')).toBeInTheDocument();
  });
});
