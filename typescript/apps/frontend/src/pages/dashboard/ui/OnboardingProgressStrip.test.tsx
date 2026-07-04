import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { JSX } from 'react';
import { describe, expect, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts?.completed !== undefined && opts?.total !== undefined) {
        return `${key}:${opts.completed}/${opts.total}`;
      }
      if (opts?.step !== undefined) {
        return `${key}:${opts.step}`;
      }
      return key;
    },
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

import { OnboardingProgressStrip } from './OnboardingProgressStrip.tsx';

const COMPLETED_STEPS: number = 2;
const TOTAL_STEPS: number = 4;
const EXPECTED_PROGRESS_PERCENT: number = 50;
const PERCENT_FULL: number = 100;

const DEFAULT_PROPS = {
  completedSteps: COMPLETED_STEPS,
  totalSteps: TOTAL_STEPS,
  nextStepLabel: 'Upload Resume',
  nextStepRoute: '/attachments',
} as const;

describe('OnboardingProgressStrip', () => {
  test('renders correct step count', () => {
    render(<OnboardingProgressStrip {...DEFAULT_PROPS} />);
    expect(screen.getByText('stage.gettingStarted.progress:2/4')).toBeInTheDocument();
  });

  test('shows next step label and route link', () => {
    render(<OnboardingProgressStrip {...DEFAULT_PROPS} />);
    expect(screen.getByText('stage.gettingStarted.next:Upload Resume')).toBeInTheDocument();
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/attachments');
  });

  test('dismiss button hides the strip', async () => {
    const user = userEvent.setup();
    render(<OnboardingProgressStrip {...DEFAULT_PROPS} />);

    const dismissBtn = screen.getByRole('button', { name: 'stage.gettingStarted.dismiss' });
    expect(dismissBtn).toBeInTheDocument();
    await user.click(dismissBtn);
    expect(screen.queryByText('stage.gettingStarted.progress:2/4')).not.toBeInTheDocument();
  });

  test('progress bar shows correct percentage value', () => {
    render(<OnboardingProgressStrip {...DEFAULT_PROPS} />);
    const progressBar = screen.getByRole('progressbar');
    expect(progressBar).toBeInTheDocument();
    // Verify the indicator reflects the correct percentage via translateX transform
    const indicator = progressBar.firstElementChild as HTMLElement;
    expect(indicator.style.transform).toBe(
      `translateX(-${PERCENT_FULL - EXPECTED_PROGRESS_PERCENT}%)`,
    );
  });
});
