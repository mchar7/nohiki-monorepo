import { render, screen } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import type * as SharedApi from '@/shared/api';
import type { ProfileResponse } from '@/shared/api';
import { useSkillBatch } from '@/shared/api';
import { ProfileViewCard } from './ProfileViewCard.tsx';

vi.mock('@/shared/api', async (importOriginal) => {
  const actual = await importOriginal<typeof SharedApi>();
  return { ...actual, useSkillBatch: vi.fn(() => ({ data: { skills: [] } })) };
});

vi.mock('./ProfileCompletenessBar.tsx', () => ({ ProfileCompletenessBar: () => null }));

const profile: ProfileResponse = {
  id: 'profile-1',
  user_id: 'user-1',
  pref_name: 'Backend Engineer',
  search_keywords: ['backend engineer', 'distributed systems'],
  user_skills: ['123e4567-e89b-12d3-a456-426614174000'],
  disallowed_keywords: [],
  work_arrangements: ['REMOTE'],
  notification_threshold: 0.7,
  auto_tailor_threshold: null,
  open_to_relocation: false,
  salary_preference: null,
  experience_preference: null,
};

describe('ProfileViewCard search terms', () => {
  test('renders search terms literally and hydrates only user skill UUIDs', () => {
    render(<ProfileViewCard profile={profile} />);

    expect(screen.getByText('backend engineer')).toBeInTheDocument();
    expect(screen.getByText('distributed systems')).toBeInTheDocument();
    expect(useSkillBatch).toHaveBeenCalledOnce();
    expect(useSkillBatch).toHaveBeenCalledWith(profile.user_skills);
    expect(useSkillBatch).not.toHaveBeenCalledWith(profile.search_keywords);
  });
  test('renders snake_case salary bounds from the profile response', () => {
    render(
      <ProfileViewCard
        profile={{
          ...profile,
          salary_preference: {
            min_salary: { minor_units: 12_000_000, currency: 'USD' },
            target_salary: { minor_units: 15_000_000, currency: 'USD' },
            preferred_frequency: 'ANNUALLY',
          },
        }}
      />,
    );

    expect(screen.getByText(/\$120,000/u)).toBeInTheDocument();
    expect(screen.getByText(/\$150,000/u)).toBeInTheDocument();
  });
  test('renders first-seen unique chips without React duplicate-key errors', () => {
    vi.mocked(useSkillBatch).mockReturnValue({
      data: {
        skills: [
          { id: 'skill-1', name: 'TypeScript', display_name: 'TypeScript' },
          { id: 'skill-2', name: 'typescript', display_name: 'TypeScript' },
          { id: 'skill-3', name: 'React', display_name: 'React' },
        ],
      },
    } as never);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const { container } = render(
      <ProfileViewCard
        profile={{
          ...profile,
          search_keywords: ['backend', 'backend', 'platform'],
          disallowed_keywords: ['frontend', 'frontend', 'support'],
          user_skills: ['skill-1', 'skill-2', 'skill-3'],
        }}
      />,
    );

    expect(
      [...container.querySelectorAll('[data-slot="badge"]')]
        .slice(0, 6)
        .map((chip) => chip.textContent),
    ).toEqual(['backend', 'platform', 'frontend', 'support', 'TypeScript', 'React']);
    expect(screen.getAllByText(/^(backend|platform)$/u)).toHaveLength(2);
    expect(screen.getAllByText(/^(frontend|support)$/u)).toHaveLength(2);
    expect(screen.getAllByText(/^(TypeScript|React)$/u)).toHaveLength(2);
    expect(consoleError).not.toHaveBeenCalled();

    consoleError.mockRestore();
  });
});
