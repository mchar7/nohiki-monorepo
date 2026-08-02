import { render, screen } from '@testing-library/react';
import { describe, expect } from 'vitest';
import { ParsedContentCard } from './ParsedContentCard.tsx';

describe('ParsedContentCard', () => {
  test('renders title and description', () => {
    render(<ParsedContentCard />);

    expect(screen.getByText('Document Analysis')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Extract skills and experience from your documents for review. Coming soon.',
      ),
    ).toBeInTheDocument();
  });

  test('renders with muted appearance', () => {
    const { container } = render(<ParsedContentCard />);

    expect(container.firstChild).toHaveClass('opacity-60');
  });
});
