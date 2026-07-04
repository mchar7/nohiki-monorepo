import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { nonNull } from '@/shared/test-utils';
import { useDashboardData } from './useDashboardData.ts';

const DEFAULT_PROFILE_COUNT = 2;
const DEFAULT_CORRELATION_COUNT = 5;
const DEFAULT_DOCUMENT_COUNT = 3;
const TOTAL_ONBOARDING_STEPS = 4;
const MIN_BROWSE_STEPS = 3;
const FIT_SCORE_BASE = 80;
const FIT_SCORE_STEP = 5;
const NEW_MATCH_COUNT = 5;
const SAVED_JOBS_COUNT = 2;
const SAVED_CORRELATIONS_INPUT = 3;

const mockUseAccount = vi.fn();
const mockUseProfiles = vi.fn();
const mockUseMyCorrelations = vi.fn();
const mockUseDocuments = vi.fn();
const mockUseLastVisit = vi.fn();
const mockUseDocumentTitle = vi.fn();

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/features/account/index.ts', () => ({ useAccount: () => mockUseAccount() }));
vi.mock('@/features/profile-management/index.ts', () => ({ useProfiles: () => mockUseProfiles() }));
vi.mock('@/features/job-matching/index.ts', () => ({
  useMyCorrelations: () => mockUseMyCorrelations(),
}));
vi.mock('@/features/document-generation/index.ts', () => ({
  useDocuments: () => mockUseDocuments(),
}));
vi.mock('@/shared/lib/index.ts', () => ({
  useDocumentTitle: (title: string) => mockUseDocumentTitle(title),
  formatRelativeTime: (date: string) => date,
}));
vi.mock('./useLastVisit.ts', async (importOriginal) => {
  const original = await importOriginal<typeof import('./useLastVisit.ts')>();
  return { ...original, useLastVisit: () => mockUseLastVisit() };
});

function makeData(count: number, type: 'profiles' | 'correlations' | 'documents') {
  if (count === 0) {
    return { data: undefined, isLoading: false };
  }
  const items = Array.from({ length: count }, (_, i) => {
    if (type === 'profiles') {
      return { id: `p-${i}`, pref_name: `P${i}`, user_skills: ['ts'] };
    }
    if (type === 'correlations') {
      return {
        id: `c-${i}`,
        fit_score: FIT_SCORE_BASE - i * FIT_SCORE_STEP,
        created_at: new Date().toISOString(),
        status: 'EVALUATED',
        listing_title: `J${i}`,
        listing_company: `C${i}`,
      };
    }
    return { request_id: `d-${i}`, status: 'completed', download_url: null };
  });
  return { data: { total: count, items }, isLoading: false };
}

function setup(
  overrides: {
    profiles?: unknown;
    correlations?: unknown;
    documents?: unknown;
    lastVisit?: unknown;
  } = {},
) {
  mockUseAccount.mockReturnValue({ data: { display_name: 'T', first_name: 'T' } });
  mockUseProfiles.mockReturnValue(
    overrides.profiles ?? makeData(DEFAULT_PROFILE_COUNT, 'profiles'),
  );
  mockUseMyCorrelations.mockReturnValue(
    overrides.correlations ?? makeData(DEFAULT_CORRELATION_COUNT, 'correlations'),
  );
  mockUseDocuments.mockReturnValue(
    overrides.documents ?? makeData(DEFAULT_DOCUMENT_COUNT, 'documents'),
  );
  mockUseLastVisit.mockReturnValue(
    overrides.lastVisit ?? { lastVisit: null, newSinceLastVisit: () => 0 },
  );
}

describe('useDashboardData — loading and counts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });
  test('sets document title', () => {
    setup();
    renderHook(() => useDashboardData());
    expect(mockUseDocumentTitle).toHaveBeenCalledWith('title');
  });
  test('returns isLoading for each loading state', () => {
    setup({ profiles: { data: undefined, isLoading: true } });
    expect(renderHook(() => useDashboardData()).result.current.isLoading).toBe(true);
    setup({ correlations: { data: undefined, isLoading: true } });
    expect(renderHook(() => useDashboardData()).result.current.isLoading).toBe(true);
    setup({ documents: { data: undefined, isLoading: true } });
    expect(renderHook(() => useDashboardData()).result.current.isLoading).toBe(true);
    setup();
    expect(renderHook(() => useDashboardData()).result.current.isLoading).toBe(false);
  });
  test('derives correct counts', () => {
    setup();
    const r = renderHook(() => useDashboardData()).result.current;
    expect(r.profileCount).toBe(DEFAULT_PROFILE_COUNT);
    expect(r.correlationCount).toBe(DEFAULT_CORRELATION_COUNT);
    expect(r.documentCount).toBe(DEFAULT_DOCUMENT_COUNT);
  });
  test('defaults counts to 0 when undefined', () => {
    setup({
      profiles: { data: undefined, isLoading: false },
      correlations: { data: undefined, isLoading: false },
      documents: { data: undefined, isLoading: false },
    });
    const r = renderHook(() => useDashboardData()).result.current;
    expect(r.profileCount).toBe(0);
    expect(r.correlationCount).toBe(0);
    expect(r.documentCount).toBe(0);
  });
});

describe('useDashboardData — stage and matches', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });
  test('computes stage correctly', () => {
    setup({ profiles: makeData(0, 'profiles') });
    expect(renderHook(() => useDashboardData()).result.current.stage).toBe('new');
    setup({ documents: makeData(0, 'documents') });
    expect(renderHook(() => useDashboardData()).result.current.stage).toBe('getting-started');
    setup();
    expect(renderHook(() => useDashboardData()).result.current.stage).toBe('active');
  });
  test('returns topMatch and latestDocument', () => {
    setup();
    const r = renderHook(() => useDashboardData()).result.current;
    expect(r.topMatch?.fit_score).toBe(FIT_SCORE_BASE);
    expect(r.latestDocument?.request_id).toBe('d-0');
    setup({ correlations: makeData(0, 'correlations'), documents: makeData(0, 'documents') });
    const r2 = renderHook(() => useDashboardData()).result.current;
    expect(r2.topMatch).toBeNull();
    expect(r2.latestDocument).toBeNull();
  });
  test('computes stats and savedJobs', () => {
    setup({ lastVisit: { lastVisit: new Date(), newSinceLastVisit: () => NEW_MATCH_COUNT } });
    const r = renderHook(() => useDashboardData()).result.current;
    expect(r.newMatchCount).toBe(NEW_MATCH_COUNT);
    expect(r.stats.jobMatches).toBe(DEFAULT_CORRELATION_COUNT);
    const c = makeData(SAVED_CORRELATIONS_INPUT, 'correlations');
    if (c.data) {
      nonNull(c.data.items[0]).status = 'SAVED';
      nonNull(c.data.items[1]).status = 'SAVED';
    }
    setup({ correlations: c });
    expect(renderHook(() => useDashboardData()).result.current.stats.savedJobs).toBe(
      SAVED_JOBS_COUNT,
    );
  });
  test('returns account data', () => {
    setup();
    expect(renderHook(() => useDashboardData()).result.current.account).toEqual({
      display_name: 'T',
      first_name: 'T',
    });
  });
});

describe('useDashboardData — onboarding progress', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });
  test('reports 0 steps for new user and 1 step with profile', () => {
    setup({
      profiles: makeData(0, 'profiles'),
      correlations: makeData(0, 'correlations'),
      documents: makeData(0, 'documents'),
    });
    const r1 = renderHook(() => useDashboardData()).result.current;
    expect(r1.onboardingProgress.completedSteps).toBe(0);
    expect(r1.onboardingProgress.totalSteps).toBe(TOTAL_ONBOARDING_STEPS);
    setup({ correlations: makeData(0, 'correlations'), documents: makeData(0, 'documents') });
    expect(
      renderHook(() => useDashboardData()).result.current.onboardingProgress.completedSteps,
    ).toBe(1);
  });
  test('marks browse step done when correlations exist or VIEWED', () => {
    setup({
      correlations: makeData(DEFAULT_CORRELATION_COUNT, 'correlations'),
      documents: makeData(0, 'documents'),
    });
    expect(
      renderHook(() => useDashboardData()).result.current.onboardingProgress.completedSteps,
    ).toBeGreaterThanOrEqual(MIN_BROWSE_STEPS);
    const c = makeData(1, 'correlations');
    if (c.data) {
      nonNull(c.data.items[0]).status = 'VIEWED';
    }
    setup({ correlations: c, documents: makeData(0, 'documents') });
    expect(
      renderHook(() => useDashboardData()).result.current.onboardingProgress.completedSteps,
    ).toBe(MIN_BROWSE_STEPS);
  });
  test('reports all steps complete when all conditions met', () => {
    const c2 = makeData(DEFAULT_CORRELATION_COUNT, 'correlations');
    if (c2.data) {
      nonNull(c2.data.items[0]).status = 'VIEWED';
    }
    setup({ correlations: c2 });
    expect(
      renderHook(() => useDashboardData()).result.current.onboardingProgress.completedSteps,
    ).toBe(TOTAL_ONBOARDING_STEPS);
  });
});
