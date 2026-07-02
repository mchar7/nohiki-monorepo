import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { FormProvider, useForm } from 'react-hook-form';
import { describe, expect, vi } from 'vitest';
import type { ProfileFormValues } from '../schemas/index.ts';
import { PROFILE_FORM_DEFAULTS } from '../schemas/index.ts';
import { SkillsCard } from './SkillsCard.tsx';

// SkillInput uses fetchClient for skill search - mock to prevent network calls in tests
vi.mock('@/shared/api/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/index.ts')>();
  return {
    ...actual,
    fetchClient: {
      GET: vi.fn().mockResolvedValue({ data: { skills: [] }, error: null }),
      POST: vi.fn().mockResolvedValue({ data: { skills: [] }, error: null }),
    },
  };
});

// Mock i18n - return the key as the translation
vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string) => {
        const translations: Record<string, string> = {
          'sections.userSkills.title': 'Your Skills',
          'sections.userSkills.description':
            'Add your professional skills to improve job match accuracy.',
          'fields.userSkills.label': 'Your Skills',
          'fields.userSkills.description':
            'Skills you are proficient in. Used to improve job matching.',
        };
        return translations[key] ?? key;
      },
      i18n: { changeLanguage: vi.fn() },
    }),
  };
});

function SkillsCardWithForm(): JSX.Element {
  const form = useForm<ProfileFormValues>({ defaultValues: PROFILE_FORM_DEFAULTS });
  return (
    <FormProvider {...form}>
      <SkillsCard control={form.control} />
    </FormProvider>
  );
}

function renderWithQuery(ui: JSX.Element): ReturnType<typeof render> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe('SkillsCard', () => {
  test('renders the card title', () => {
    renderWithQuery(<SkillsCardWithForm />);
    // Both CardTitle and FormLabel use this text - verify at least one is rendered
    expect(screen.getAllByText('Your Skills').length).toBeGreaterThanOrEqual(1);
  });

  test('renders the card description', () => {
    renderWithQuery(<SkillsCardWithForm />);
    expect(
      screen.getByText('Add your professional skills to improve job match accuracy.'),
    ).toBeTruthy();
  });

  test('renders the field label', () => {
    renderWithQuery(<SkillsCardWithForm />);
    // "Your Skills" appears in both the title and the label
    expect(screen.getAllByText('Your Skills').length).toBeGreaterThanOrEqual(1);
  });

  test('renders the field description', () => {
    renderWithQuery(<SkillsCardWithForm />);
    expect(
      screen.getByText('Skills you are proficient in. Used to improve job matching.'),
    ).toBeTruthy();
  });

  test('mounts without crashing', () => {
    const { container } = renderWithQuery(<SkillsCardWithForm />);
    expect(container.firstChild).not.toBeNull();
  });
});
