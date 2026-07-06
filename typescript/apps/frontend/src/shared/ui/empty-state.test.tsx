import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FileText } from 'lucide-react';
import { describe, expect, vi } from 'vitest';
import { EmptyState } from './empty-state.tsx';

describe('EmptyState rendering', () => {
  test('renders with title and icon', () => {
    render(<EmptyState icon={FileText} title="No items found" />);

    expect(screen.getByText('No items found')).toBeInTheDocument();
  });

  test('renders description when provided', () => {
    render(
      <EmptyState
        icon={FileText}
        title="No items"
        description="Try adding some items to get started"
      />,
    );

    expect(screen.getByText('Try adding some items to get started')).toBeInTheDocument();
  });

  test('renders children when provided', () => {
    render(
      <EmptyState icon={FileText} title="No items">
        <div data-testid="custom-content">Custom content</div>
      </EmptyState>,
    );

    expect(screen.getByTestId('custom-content')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    const { container } = render(
      <EmptyState icon={FileText} title="No items" className="custom-class" />,
    );

    expect(container.firstChild).toHaveClass('custom-class');
  });
});

describe('EmptyState variants and sizes', () => {
  test('renders with different sizes', () => {
    const { rerender } = render(<EmptyState icon={FileText} title="Test" size="sm" />);
    expect(screen.getByText('Test')).toBeInTheDocument();

    rerender(<EmptyState icon={FileText} title="Test" size="md" />);
    expect(screen.getByText('Test')).toBeInTheDocument();

    rerender(<EmptyState icon={FileText} title="Test" size="lg" />);
    expect(screen.getByText('Test')).toBeInTheDocument();
  });

  test('renders with different variants', () => {
    const { rerender } = render(<EmptyState icon={FileText} title="Test" variant="default" />);
    expect(screen.getByText('Test')).toBeInTheDocument();

    rerender(<EmptyState icon={FileText} title="Test" variant="card" />);
    expect(screen.getByText('Test')).toBeInTheDocument();

    rerender(<EmptyState icon={FileText} title="Test" variant="inline" />);
    expect(screen.getByText('Test')).toBeInTheDocument();
  });
});

describe('EmptyState actions', () => {
  test('renders action button when provided', async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <EmptyState
        icon={FileText}
        title="No items"
        action={{ label: 'Add Item', onClick: handleClick }}
      />,
    );

    const button = screen.getByRole('button', { name: 'Add Item' });
    expect(button).toBeInTheDocument();

    await user.click(button);
    expect(handleClick).toHaveBeenCalled();
  });

  test('renders secondary action when provided', async () => {
    const user = userEvent.setup();
    const handlePrimary = vi.fn();
    const handleSecondary = vi.fn();

    render(
      <EmptyState
        icon={FileText}
        title="No items"
        action={{ label: 'Add Item', onClick: handlePrimary }}
        secondaryAction={{ label: 'Learn More', onClick: handleSecondary }}
      />,
    );

    const secondaryButton = screen.getByRole('button', { name: 'Learn More' });
    await user.click(secondaryButton);
    expect(handleSecondary).toHaveBeenCalled();
  });

  test('applies action button variant', () => {
    render(
      <EmptyState
        icon={FileText}
        title="Test"
        action={{ label: 'Action', onClick: vi.fn(), variant: 'outline' }}
      />,
    );

    const button = screen.getByRole('button', { name: 'Action' });
    expect(button).toBeInTheDocument();
  });
});
