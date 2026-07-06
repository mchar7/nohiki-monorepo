import { render } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { configureAxe } from 'vitest-axe';
import { i18n } from '@/test/setup.ts';
import { SortSelect } from './sort-select.tsx';

const SORT_OPTIONS = [
  { value: 'name', label: 'Name' },
  { value: 'date', label: 'Date' },
] as const;

describe('SortSelect - accessibility', () => {
  test('has no accessibility violations', async () => {
    // Disable region rule: component tests render in isolation without landmarks
    const isolatedAxe = configureAxe({ rules: { region: { enabled: false } } });
    const { container } = render(
      <I18nextProvider i18n={i18n}>
        <SortSelect
          options={SORT_OPTIONS}
          value="name"
          direction="asc"
          onValueChange={vi.fn()}
          onDirectionChange={vi.fn()}
        />
      </I18nextProvider>,
    );
    const results = await isolatedAxe(container);
    expect(results).toHaveNoViolations();
  });
});
