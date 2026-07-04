const IMPROVE_CTA_RE = /missingSkills\.improve\.cta/iu;
const COMING_SOON_CTA_RE = /missingSkills\.comingSoon\.cta/iu;

import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { describe, expect, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
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

import { CommonMissingSkillsWidget } from './CommonMissingSkillsWidget.tsx';

const TEST_PROFILE_ID = 'profile-abc-123';

describe('CommonMissingSkillsWidget', () => {
  test('renders "Improve Your Matches" card when hasSkills is false', () => {
    render(<CommonMissingSkillsWidget hasSkills={false} />);

    expect(screen.getByText('missingSkills.improve.title')).toBeInTheDocument();
    expect(screen.getByText('missingSkills.improve.description')).toBeInTheDocument();
  });

  test('CTA links to profile edit page when profileId is provided', () => {
    render(<CommonMissingSkillsWidget hasSkills={false} profileId={TEST_PROFILE_ID} />);

    const link = screen.getByRole('link', { name: IMPROVE_CTA_RE });
    expect(link).toHaveAttribute('href', `/profiles/${TEST_PROFILE_ID}`);
  });

  test('CTA links to profiles list when no profileId is provided', () => {
    render(<CommonMissingSkillsWidget hasSkills={false} />);

    const link = screen.getByRole('link', { name: IMPROVE_CTA_RE });
    expect(link).toHaveAttribute('href', '/profiles');
  });

  test('renders "coming soon" card when hasSkills is true', () => {
    render(<CommonMissingSkillsWidget hasSkills={true} />);

    expect(screen.getByText('missingSkills.comingSoon.title')).toBeInTheDocument();
    expect(screen.getByText('missingSkills.comingSoon.description')).toBeInTheDocument();
  });

  test('CTA links to jobs page when hasSkills is true', () => {
    render(<CommonMissingSkillsWidget hasSkills={true} />);

    const link = screen.getByRole('link', { name: COMING_SOON_CTA_RE });
    expect(link).toHaveAttribute('href', '/jobs');
  });
});
