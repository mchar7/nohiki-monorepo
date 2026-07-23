import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import { DashboardSkeleton } from './DashboardSkeleton.tsx';

/** Number of stat card placeholders expected in the skeleton */
const STAT_CARD_COUNT = 4;
/** Number of highlight card placeholders expected */
const HIGHLIGHT_CARD_COUNT = 2;

function renderComponent(): ReturnType<typeof render> {
  return render(
    <I18nextProvider i18n={i18n}>
      <DashboardSkeleton />
    </I18nextProvider>,
  );
}

describe('DashboardSkeleton', () => {
  test('renders with aria-busy and aria-label for accessibility', () => {
    renderComponent();

    const skeleton = screen.getByLabelText('Loading dashboard content');
    expect(skeleton).toBeInTheDocument();
    expect(skeleton).toHaveAttribute('aria-busy', 'true');
  });

  test('renders stat card skeletons', () => {
    const { container } = renderComponent();

    // Stat cards grid: 4 cards, each containing skeleton elements
    const statCardsGrid = container.querySelector('.grid.grid-cols-2');
    expect(statCardsGrid).toBeInTheDocument();
    const statCards = statCardsGrid?.querySelectorAll(':scope > div');
    expect(statCards).toHaveLength(STAT_CARD_COUNT);
  });

  test('renders highlight card skeletons', () => {
    const { container } = renderComponent();

    // Highlight cards grid: 2 cards
    const highlightGrid = container.querySelector('.grid.grid-cols-1.md\\:grid-cols-2');
    expect(highlightGrid).toBeInTheDocument();
    const highlightCards = highlightGrid?.querySelectorAll(':scope > div');
    expect(highlightCards).toHaveLength(HIGHLIGHT_CARD_COUNT);
  });

  test('renders chart skeleton placeholder', () => {
    const { container } = renderComponent();

    // Chart skeleton: a card with a large skeleton (h-44)
    const chartSkeleton = container.querySelector('.h-44');
    expect(chartSkeleton).toBeInTheDocument();
  });
});
