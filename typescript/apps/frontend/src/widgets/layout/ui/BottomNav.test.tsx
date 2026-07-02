import { render } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { wrapWithRouter } from '@/shared/test-utils/index.ts';
import { i18n } from '@/test/setup.ts';
import { BottomNav } from './BottomNav.tsx';

vi.mock('@/shared/ui/sidebar.tsx', () => ({
  useSidebar: () => ({ openMobile: false }),
}));

describe('BottomNav - accessibility', () => {
  test('has no accessibility violations', async () => {
    const { container } = render(
      await wrapWithRouter(
        <I18nextProvider i18n={i18n}>
          <BottomNav />
        </I18nextProvider>,
      ),
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
