import type * as TanStackReactRouter from '@tanstack/react-router';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, vi } from 'vitest';
import type * as JobMatching from '@/features/job-matching/index.ts';
import type { JobCorrelationResponse } from '@/shared/api';
import { MatchDetail } from './MatchDetail.tsx';

const {
  useCorrelation,
  useRecordFeedback,
  useScoreFeedback,
  useAdjustScore,
  useTemplateFamilies,
  useGenerateTailoredDocument,
  useDocumentSSE,
} = vi.hoisted(() => ({
  useCorrelation: vi.fn(),
  useRecordFeedback: vi.fn(),
  useScoreFeedback: vi.fn(),
  useAdjustScore: vi.fn(),
  useTemplateFamilies: vi.fn(),
  useGenerateTailoredDocument: vi.fn(),
  useDocumentSSE: vi.fn(),
}));

Object.defineProperties(HTMLElement.prototype, {
  hasPointerCapture: { configurable: true, value: vi.fn(() => false) },
  releasePointerCapture: { configurable: true, value: vi.fn() },
  scrollIntoView: { configurable: true, value: vi.fn() },
  setPointerCapture: { configurable: true, value: vi.fn() },
});

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof TanStackReactRouter>();
  return {
    ...actual,
    useNavigate: () => () => Promise.resolve(),
    useParams: () => ({ correlationId: 'correlation-42' }),
    useRouter: () => ({
      state: { location: { pathname: '/jobs/matches/correlation-42' } },
      subscribe: () => () => undefined,
    }),
    Link: ({ children, to, ...props }: { children: ReactNode; to: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  };
});

vi.mock('@/features/job-matching/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof JobMatching>();
  return {
    ...actual,
    useCorrelation,
    useRecordFeedback,
    useScoreFeedback,
    useAdjustScore,
  };
});
vi.mock('@/features/omakase/document-builder', () => ({ useTemplateFamilies }));
vi.mock('@/features/document-generation', () => ({
  useGenerateTailoredDocument,
  useDocumentSSE,
}));

const correlation: JobCorrelationResponse = {
  id: 'response-correlation-id',
  pref_id: 'pref-1',
  listing_id: 'listing-1',
  fit_score: 0.85,
  status: 'EVALUATED',
  score_breakdown: {},
  listing_title: 'Principal Engineer',
  listing_company: 'Example Co',
  listing_url: 'https://example.com/jobs/1',
  listing_location: 'Remote',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};

const mutate = vi.fn();

describe('MatchDetail tailored document integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCorrelation.mockReturnValue({ data: correlation, isLoading: false, error: null });
    for (const hook of [useRecordFeedback, useScoreFeedback, useAdjustScore]) {
      hook.mockReturnValue({ mutate: vi.fn(), isPending: false });
    }
    useTemplateFamilies.mockReturnValue({
      data: {
        items: [
          {
            id: 'family-cover-letter',
            name: 'Cover Letter',
            namespace: 'cover_letter',
            description: null,
            latest_version: { id: 'version-1' },
          },
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    useGenerateTailoredDocument.mockReturnValue({
      mutate,
      reset: vi.fn(),
      isPending: false,
      error: null,
    });
    useDocumentSSE.mockReturnValue({
      status: 'connecting',
      downloadUrl: null,
      error: null,
      progress: 0,
      disconnect: vi.fn(),
      isConnected: false,
    });
  });

  test('supplies the route correlation ID to the tailored-document action', async () => {
    const user = userEvent.setup();
    render(<MatchDetail />);

    await user.click(screen.getByRole('button', { name: 'Tailor a document' }));
    expect(screen.getByText('For Principal Engineer at Example Co')).toBeVisible();
    await user.click(screen.getByRole('combobox', { name: 'Template' }));
    await user.click(screen.getByRole('option', { name: 'Cover Letter' }));
    await user.click(screen.getByRole('button', { name: 'Generate document' }));

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({ job_correlation_id: 'correlation-42' }),
      }),
      expect.anything(),
    );
  });
});
