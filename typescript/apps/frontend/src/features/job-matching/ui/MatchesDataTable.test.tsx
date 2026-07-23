import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import { MatchesDataTable } from './MatchesDataTable.tsx';

describe('MatchesDataTable filtered empty state', () => {
  test('explains that filters removed all matches and offers to clear them', async () => {
    const user = userEvent.setup();
    const onClearFilters = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <I18nextProvider i18n={i18n}>
          <MatchesDataTable
            data={[]}
            hasProfiles={true}
            hasActiveFilters={true}
            onRefetch={vi.fn()}
            onClearFilters={onClearFilters}
            onStatusAction={vi.fn()}
            isStatusActionPending={false}
          />
        </I18nextProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByRole('status')).toHaveTextContent('No matches meet your filters');
    expect(screen.queryByRole('button', { name: 'Refresh' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear Filters' }));

    expect(onClearFilters).toHaveBeenCalledOnce();
  });
});
