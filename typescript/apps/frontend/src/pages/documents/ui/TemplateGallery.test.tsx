import type { UseQueryResult } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import { useTemplateFamilies } from '@/features/omakase/document-builder';
import type { TemplateFamilyResponse } from '@/shared/api';
import {
  makeQueryEmpty,
  makeQueryError,
  makeQueryLoading,
  makeQuerySuccess,
} from '@/shared/test-utils';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { TemplateGallery } from './TemplateGallery.tsx';

vi.mock('@/features/omakase/document-builder');

const EXPECTED_SKELETON_COUNT = 6;
const TRY_AGAIN_PATTERN = /try again/iu;

type FamiliesResult = ReturnType<typeof useTemplateFamilies>;
type FamiliesData =
  FamiliesResult extends UseQueryResult<infer D, infer _E> ? Exclude<D, undefined> : never;

const mockTemplates: TemplateFamilyResponse[] = [
  {
    id: '1',
    name: 'modern_resume',
    display_name: 'Modern Résumé',
    namespace: 'resume',
    description: 'A clean design',
  },
  {
    id: '2',
    name: 'classic_cover_letter',
    display_name: 'Classic Cover Letter',
    namespace: 'cover_letter',
    description: 'Traditional layout',
  },
];

interface MockHookOptions {
  readonly data?: FamiliesData;
  readonly isLoading?: boolean;
  readonly error?: Error;
}

function mockHook({ data, isLoading, error }: MockHookOptions): void {
  if (isLoading === true) {
    vi.mocked(useTemplateFamilies).mockReturnValue(
      makeQueryLoading<FamiliesData>() as FamiliesResult,
    );
    return;
  }
  if (error !== undefined) {
    vi.mocked(useTemplateFamilies).mockReturnValue(
      makeQueryError<FamiliesData>(error) as FamiliesResult,
    );
    return;
  }
  if (data !== undefined) {
    vi.mocked(useTemplateFamilies).mockReturnValue(
      makeQuerySuccess<FamiliesData>(data) as FamiliesResult,
    );
    return;
  }
  vi.mocked(useTemplateFamilies).mockReturnValue(makeQueryEmpty<FamiliesData>() as FamiliesResult);
}

async function renderGallery(): Promise<ReturnType<typeof render>> {
  const ui = await wrapWithRouter(
    <I18nextProvider i18n={i18n}>
      <TemplateGallery />
    </I18nextProvider>,
  );
  return render(ui);
}

describe('TemplateGallery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders loading state', async () => {
    mockHook({ isLoading: true });
    const { container } = await renderGallery();
    expect(container.querySelectorAll('.animate-pulse')).toHaveLength(EXPECTED_SKELETON_COUNT);
  });

  test('renders error state', async () => {
    mockHook({ error: new Error('Failed') });
    await renderGallery();
    expect(screen.getByText('Failed to load templates')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: TRY_AGAIN_PATTERN })).toBeInTheDocument();
  });

  test('renders empty state when no templates exist', async () => {
    mockHook({
      data: {
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      },
    });
    await renderGallery();
    expect(screen.getByText('No templates found')).toBeInTheDocument();
    expect(screen.getByText('There are no templates available at the moment')).toBeInTheDocument();
  });

  test('renders template cards', async () => {
    mockHook({
      data: {
        items: mockTemplates,
        total: 2,
        page: 1,
        page_size: 20,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });
    await renderGallery();
    expect(screen.getByText('Modern Résumé')).toBeInTheDocument();
    expect(screen.getByText('Classic Cover Letter')).toBeInTheDocument();
    expect(screen.queryByText('modern_resume')).not.toBeInTheDocument();
  });

  test('filters templates by search query', async () => {
    mockHook({
      data: {
        items: mockTemplates,
        total: 2,
        page: 1,
        page_size: 20,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });
    await renderGallery();
    const user = userEvent.setup();
    const searchInput = screen.getByPlaceholderText('Search templates...');
    await user.type(searchInput, 'résumé');
    expect(screen.getByText('Modern Résumé')).toBeInTheDocument();
    expect(screen.queryByText('Classic Cover Letter')).not.toBeInTheDocument();
    expect(screen.queryByText('modern_resume')).not.toBeInTheDocument();
  });
});
