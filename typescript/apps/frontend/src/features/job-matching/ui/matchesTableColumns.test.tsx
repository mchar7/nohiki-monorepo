import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router';
import { flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { TFunction } from 'i18next';
import type { JSX } from 'react';
import { I18nextProvider, useTranslation } from 'react-i18next';
import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import type { FeedbackType, JobCorrelationResponse } from '@/shared/api';
import { TooltipProvider } from '@/shared/ui/tooltip.tsx';
import { i18n } from '@/test/i18n-setup.ts';
import { createColumns } from './matchesTableColumns.tsx';

// Mock useIsMobileLayout
const mockUseIsMobileLayout = vi.fn<() => boolean>().mockReturnValue(false);

vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    useIsMobileLayout: () => mockUseIsMobileLayout(),
  };
});

const mockData: JobCorrelationResponse[] = [
  {
    id: 'corr-1',
    listing_id: 'job-1',
    pref_id: 'prof-1',
    fit_score: 85,
    listing_title: 'Software Engineer',
    listing_company: 'Tech Corp',
    listing_location: 'San Francisco, CA',
    listing_url: 'https://example.com/job',
    status: 'PENDING',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    score_breakdown: {},
  },
];

// Helper to render table with routing context
function TestTable({
  onFeedback,
  onStatusAction = vi.fn(),
  isStatusActionPending = false,
}: {
  readonly onFeedback?: (correlationId: string, type: 'like' | 'dislike') => Promise<void>;
  readonly onStatusAction?: (correlationId: string, type: FeedbackType) => void;
  readonly isStatusActionPending?: boolean;
}): JSX.Element {
  const { t } = useTranslation(['jobs', 'common']);
  const columns = createColumns(t, onFeedback, onStatusAction, isStatusActionPending);

  const table = useReactTable({
    data: mockData,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <table>
      <thead>
        {table.getHeaderGroups().map((headerGroup) => (
          <tr key={headerGroup.id}>
            {headerGroup.headers.map((header) => (
              <th key={header.id}>
                {header.isPlaceholder
                  ? null
                  : flexRender(header.column.columnDef.header, header.getContext())}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id}>
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function renderTableWithRouter(
  onFeedback?: (correlationId: string, type: 'like' | 'dislike') => Promise<void>,
  onStatusAction?: (correlationId: string, type: FeedbackType) => void,
  isStatusActionPending = false,
) {
  const rootRoute = createRootRoute();
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    component: () => (
      <TestTable
        onFeedback={onFeedback}
        onStatusAction={onStatusAction}
        isStatusActionPending={isStatusActionPending}
      />
    ),
  });

  const routeTree = rootRoute.addChildren([indexRoute]);
  const history = createMemoryHistory({ initialEntries: ['/'] });
  const router = createRouter({ routeTree, history });

  return render(
    <I18nextProvider i18n={i18n}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </I18nextProvider>,
  );
}

describe('matchesTableColumns', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    mockUseIsMobileLayout.mockReturnValue(false);
  });

  test('defines correct number of columns', () => {
    const columns = createColumns(
      i18n.t as TFunction<['jobs', 'common']>,
      undefined,
      vi.fn(),
      false,
    );
    expect(columns).toHaveLength(7);
    expect(columns.map((c) => c.id || ('accessorKey' in c ? c.accessorKey : ''))).toEqual([
      'select',
      'fit_score',
      'listing_title',
      'listing_location',
      'status',
      'created_at',
      'actions',
    ]);
  });

  test('renders all desktop columns correctly', async () => {
    // biome-ignore lint/suspicious/useAwait: act() requires await in React 18
    await act(async () => {
      renderTableWithRouter();
    });

    // Headers
    expect(screen.getByText('Match score')).toBeInTheDocument();
    expect(screen.getByText('Company')).toBeInTheDocument();
    expect(screen.getByText('Location')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Matched')).toBeInTheDocument();

    // Data
    expect(screen.getByText('85 / 100')).toBeInTheDocument();
    expect(screen.queryByText('85%')).not.toBeInTheDocument();
    expect(screen.getByText('Software Engineer')).toBeInTheDocument();
    expect(screen.getByText('Tech Corp')).toBeInTheDocument();
    expect(screen.getByText('San Francisco, CA')).toBeInTheDocument();
  });

  test('renders feedback actions when onFeedback is provided', async () => {
    // biome-ignore lint/suspicious/useAwait: act() requires await in React 18
    await act(async () => {
      renderTableWithRouter(vi.fn());
    });

    expect(screen.getByText('Like')).toBeInTheDocument();
    expect(screen.getByText('Dislike')).toBeInTheDocument();
  });

  test('does not render feedback actions when onFeedback is undefined', async () => {
    // biome-ignore lint/suspicious/useAwait: act() requires await in React 18
    await act(async () => {
      renderTableWithRouter();
    });

    expect(screen.queryByText('Like')).not.toBeInTheDocument();
    expect(screen.queryByText('Dislike')).not.toBeInTheDocument();
  });

  describe('ActionsMenu - desktop', () => {
    test('renders actions in DropdownMenu', async () => {
      const user = userEvent.setup();
      // biome-ignore lint/suspicious/useAwait: act() requires await in React 18
      await act(async () => {
        renderTableWithRouter();
      });

      // Click more actions trigger
      await user.click(screen.getByRole('button', { name: 'More options' }));

      await waitFor(() => {
        expect(screen.getByText('View Details')).toBeInTheDocument();
        expect(screen.getByText('View Original Posting')).toBeInTheDocument();
        expect(screen.getByText('Save')).toBeInTheDocument();
        expect(screen.getByText('Mark Applied')).toBeInTheDocument();
        expect(screen.getByText('Dismiss')).toBeInTheDocument();
      });

      // Desktop does not render sheet title
      expect(screen.queryByText('Actions')).not.toBeInTheDocument();
    });

    test.each([
      ['Save', 'SAVED'],
      ['Mark Applied', 'APPLIED'],
      ['Dismiss', 'DISMISSED'],
    ] as const)('sends exact %s status action payload', async (label, feedbackType) => {
      const user = userEvent.setup();
      const onStatusAction = vi.fn();
      renderTableWithRouter(undefined, onStatusAction);

      await user.click(await screen.findByRole('button', { name: 'More options' }));
      await user.click(await screen.findByText(label));

      expect(onStatusAction).toHaveBeenCalledOnce();
      expect(onStatusAction).toHaveBeenCalledWith('corr-1', feedbackType);
    });

    test('suppresses every status action while one is pending', async () => {
      const user = userEvent.setup();
      const onStatusAction = vi.fn();
      renderTableWithRouter(undefined, onStatusAction, true);

      await user.click(await screen.findByRole('button', { name: 'More options' }));

      for (const label of ['Save', 'Mark Applied', 'Dismiss']) {
        expect(await screen.findByText(label)).toHaveAttribute('data-disabled');
      }
      expect(onStatusAction).not.toHaveBeenCalled();
    });

    test('applies destructive styling to dismiss action', async () => {
      const user = userEvent.setup();
      // biome-ignore lint/suspicious/useAwait: async act flushes TanStack table/menu state triggered during render.
      await act(async () => {
        renderTableWithRouter();
      });

      await user.click(screen.getByRole('button', { name: 'More options' }));

      const dismissItem = await screen.findByText('Dismiss');
      expect(dismissItem.className).toContain('text-destructive');
    });

    test.each(['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'not a URL'])(
      'does not open unsafe or malformed listing URL %s',
      async (listingUrl) => {
        const user = userEvent.setup();
        const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
        const original = mockData[0];
        if (!original) throw new Error('expected a listing row');
        mockData[0] = { ...original, listing_url: listingUrl };
        renderTableWithRouter();

        await user.click(await screen.findByRole('button', { name: 'More options' }));
        await user.click(await screen.findByText('View Original Posting'));

        expect(openSpy).not.toHaveBeenCalled();
        mockData[0] = { ...original, listing_url: 'https://example.com/job' };
        openSpy.mockRestore();
      },
    );

    test('opens a valid HTTPS listing URL', async () => {
      const user = userEvent.setup();
      const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
      renderTableWithRouter();

      await user.click(await screen.findByRole('button', { name: 'More options' }));
      await user.click(await screen.findByText('View Original Posting'));

      expect(openSpy).toHaveBeenCalledWith(
        'https://example.com/job',
        '_blank',
        'noopener,noreferrer',
      );
      openSpy.mockRestore();
    });
  });

  describe('ActionsMenu - mobile', () => {
    beforeEach(() => {
      mockUseIsMobileLayout.mockReturnValue(true);
    });

    test('renders actions in BottomSheet with title', async () => {
      const user = userEvent.setup();
      // biome-ignore lint/suspicious/useAwait: async act flushes TanStack table/menu state triggered during render.
      await act(async () => {
        renderTableWithRouter();
      });

      await user.click(screen.getByRole('button', { name: 'More options' }));

      await waitFor(() => {
        // Mobile renders sheet title
        expect(screen.getByText('Actions')).toBeInTheDocument();

        expect(screen.getByText('View Details')).toBeInTheDocument();
        expect(screen.getByText('View Original Posting')).toBeInTheDocument();
        expect(screen.getByText('Save')).toBeInTheDocument();
        expect(screen.getByText('Mark Applied')).toBeInTheDocument();
        expect(screen.getByText('Dismiss')).toBeInTheDocument();
      });
    });
  });
});
