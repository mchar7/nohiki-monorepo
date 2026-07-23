import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, test } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import { MatchesStatsCards } from './MatchesStatsCards.tsx';

describe('MatchesStatsCards', () => {
  test('keeps the high-quality ratio as a true percentage', () => {
    render(
      <I18nextProvider i18n={i18n}>
        <MatchesStatsCards stats={{ total: 8, highQuality: 6, newThisWeek: 0, saved: 2 }} />
      </I18nextProvider>,
    );

    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(screen.queryByText('75 / 100')).not.toBeInTheDocument();
  });
});
