import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type React from 'react';
import type { JSX } from 'react';
import { FormProvider, useForm } from 'react-hook-form';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { ProfileFormValues } from '../schemas/index.ts';
import type * as ProfileSchema from '../schemas/profile.schema.ts';
import { KeywordsCard } from './KeywordsCard.tsx';

// Mock responsive layout
vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: vi.fn().mockReturnValue(false),
  };
});

// Mock inputs while preserving the accessible form-control contract.
vi.mock('@/shared/ui/TagInput.tsx', () => ({
  TagInput: vi.fn(({ id, maxTags, value }: { id?: string; maxTags: number; value?: string[] }) => (
    <input
      id={id}
      data-testid="tag-input"
      data-max-tags={maxTags}
      value={(value ?? []).join(',')}
      readOnly
    />
  )),
}));

vi.mock('@/shared/ui/skill-input/SkillInput.tsx', () => ({
  SkillInput: vi.fn(() => <div data-testid="skill-input" />),
}));

// We want to verify that it uses the constant KEYWORDS_MAX_ITEMS.
// To make it FAIL, we mock KEYWORDS_MAX_ITEMS to something else.
vi.mock('../schemas/profile.schema', async (importOriginal) => {
  const actual = await importOriginal<typeof ProfileSchema>();
  return {
    ...actual,
    KEYWORDS_MAX_ITEMS: 99,
  };
});

const SEARCH_KEYWORDS_REGEX = /Search Keywords/iu;

describe('KeywordsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const createWrapper = (): (({ children }: { children: React.ReactNode }) => JSX.Element) => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    return ({ children }: { children: React.ReactNode }): JSX.Element => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };

  const TestWrapper = (): JSX.Element => {
    const methods = useForm<ProfileFormValues>({
      defaultValues: {
        search_keywords: [],
        disallowed_keywords: [],
      },
    });
    return (
      <FormProvider {...methods}>
        <KeywordsCard control={methods.control} />
      </FormProvider>
    );
  };

  test('renders TagInput rather than SkillInput for search keywords', () => {
    render(<TestWrapper />, { wrapper: createWrapper() });
    expect(screen.getAllByTestId('tag-input')).toHaveLength(2);
    expect(screen.queryByTestId('skill-input')).not.toBeInTheDocument();
  });

  test('search keyword TagInput receives the shared item limit', () => {
    render(<TestWrapper />, { wrapper: createWrapper() });
    expect(screen.getAllByTestId('tag-input')[0]).toHaveAttribute('data-max-tags', '99');
  });

  test('associates the Search Keywords label with its TagInput', () => {
    render(<TestWrapper />, { wrapper: createWrapper() });
    expect(screen.getByRole('textbox', { name: /^Search Keywords$/iu })).toBeInTheDocument();
  });

  test('renders the localized Search Keywords heading and field label', () => {
    render(<TestWrapper />, { wrapper: createWrapper() });
    expect(screen.getAllByText(SEARCH_KEYWORDS_REGEX).length).toBeGreaterThanOrEqual(2);
  });
});
