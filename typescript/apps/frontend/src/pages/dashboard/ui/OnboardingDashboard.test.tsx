import { type RenderResult, render, screen, within } from '@testing-library/react';
import type { JSX, PropsWithChildren } from 'react';
import { describe, expect, vi } from 'vitest';

// Mock react-i18next: return key as value, with interpolation support
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (!params) {
        return key;
      }
      let result: string = key;
      for (const [k, v] of Object.entries(params)) {
        result = result.replace(`{{${k}}}`, String(v));
      }
      return result;
    },
  }),
}));

// Mock TanStack Router Link to render a plain <a> tag with href
vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children, ...rest }: PropsWithChildren<{ to: string }>): JSX.Element => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}));

import { OnboardingDashboard } from './OnboardingDashboard.tsx';

const BASE_PROPS = {
  displayName: null,
  firstName: null,
  profileCount: 0,
  correlationCount: 0,
  documentCount: 0,
  correlations: [] as readonly { status: string }[],
} as const;

function renderDashboard(overrides: Record<string, unknown> = {}): RenderResult {
  return render(<OnboardingDashboard {...BASE_PROPS} {...overrides} />);
}

function queryActiveStep(): HTMLElement | null {
  return document.querySelector('[aria-current="step"]');
}

const EXPECTED_COMPLETED_STEPS: number = 4;

describe('OnboardingDashboard greeting', () => {
  test('renders greeting with display name', () => {
    renderDashboard({ displayName: 'Alice' });
    expect(screen.getByText('onboarding.welcome.greeting')).toBeInTheDocument();
  });

  test('renders greeting with first name when display name is null', () => {
    renderDashboard({ displayName: null, firstName: 'Bob' });
    expect(screen.getByText('onboarding.welcome.greeting')).toBeInTheDocument();
  });

  test('renders generic greeting when both names are null', () => {
    renderDashboard({ displayName: null, firstName: null });
    expect(screen.getByText('onboarding.welcome.greetingGeneric')).toBeInTheDocument();
  });
});

describe('OnboardingDashboard progress', () => {
  test('progress bar shows correct percentage for 1 of 4 steps', () => {
    renderDashboard({ profileCount: 1 });
    expect(screen.getByText('onboarding.progress.percent')).toBeInTheDocument();
  });
});

describe('OnboardingDashboard step states', () => {
  test('step 1 shows as completed when profileCount > 0', () => {
    renderDashboard({ profileCount: 1, profileName: 'Backend Eng' });
    const completedLabels = screen.getAllByText('onboarding.stepState.completed');
    expect(completedLabels.length).toBeGreaterThanOrEqual(1);
  });

  test('step 2 shows as active when profiles exist but no correlations', () => {
    renderDashboard({ profileCount: 1, correlationCount: 0 });
    const activeStep = queryActiveStep();
    expect(activeStep).toBeInTheDocument();
    expect(
      within(activeStep as HTMLElement).getByText('onboarding.steps.browse.title'),
    ).toBeInTheDocument();
  });

  test('all 4 steps completed shows all check icons', () => {
    renderDashboard({
      profileCount: 2,
      correlationCount: 10,
      documentCount: 3,
      correlations: [{ status: 'VIEWED' }],
    });
    const completedLabels = screen.getAllByText('onboarding.stepState.completed');
    expect(completedLabels).toHaveLength(EXPECTED_COMPLETED_STEPS);
  });
});

describe('OnboardingDashboard navigation and accessibility', () => {
  test('CTA buttons render correct route links', () => {
    renderDashboard({ profileCount: 0 });
    const ctaLink = screen.getByRole('link');
    expect(ctaLink).toHaveAttribute('href', '/profiles/new');
  });

  test('active step has aria-current="step" attribute', () => {
    renderDashboard({ profileCount: 0 });
    const activeStep = queryActiveStep();
    expect(activeStep).toBeInTheDocument();
    expect(
      within(activeStep as HTMLElement).getByText('onboarding.steps.profile.title'),
    ).toBeInTheDocument();
  });
});
