import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { JSX } from 'react';
import { describe, expect, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
  }),
}));

vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    to,
    className,
  }: {
    readonly children: React.ReactNode;
    readonly to: string;
    readonly className?: string;
  }): JSX.Element => (
    <a href={to} className={className}>
      {children}
    </a>
  ),
}));

import { DashboardNewMatchesBanner } from './DashboardNewMatchesBanner.tsx';

const MATCH_COUNT_ZERO: number = 0;
const MATCH_COUNT_SINGLE: number = 1;
const MATCH_COUNT_MULTIPLE: number = 7;

describe('DashboardNewMatchesBanner', () => {
  test('renders nothing when newMatchCount is 0', () => {
    const { container } = render(<DashboardNewMatchesBanner newMatchCount={MATCH_COUNT_ZERO} />);
    expect(container.firstChild).toBeNull();
  });

  test('renders banner with correct count when > 0', () => {
    render(<DashboardNewMatchesBanner newMatchCount={MATCH_COUNT_MULTIPLE} />);
    expect(screen.getByText('banner.newMatches.message:7')).toBeInTheDocument();
  });

  test('dismiss button hides the banner', async () => {
    const user = userEvent.setup();
    render(<DashboardNewMatchesBanner newMatchCount={MATCH_COUNT_SINGLE} />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'banner.newMatches.dismiss' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('banner has role="alert" for accessibility', () => {
    render(<DashboardNewMatchesBanner newMatchCount={MATCH_COUNT_MULTIPLE} />);
    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveAttribute('aria-live', 'polite');
  });

  test('"View Matches" link is present and points to matches page', () => {
    render(<DashboardNewMatchesBanner newMatchCount={MATCH_COUNT_MULTIPLE} />);
    const link = screen.getByRole('link');
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/jobs/matches');
  });
});
