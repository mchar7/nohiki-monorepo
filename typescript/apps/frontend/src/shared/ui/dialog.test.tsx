import { render } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect } from 'vitest';
import { axe } from 'vitest-axe';
import { i18n } from '@/test/setup.ts';
import { Dialog, DialogContent, DialogTitle } from './dialog.tsx';

describe('Dialog - accessibility', () => {
  test('has no accessibility violations when open', async () => {
    const { baseElement } = render(
      <I18nextProvider i18n={i18n}>
        <Dialog open={true}>
          <DialogContent>
            <DialogTitle>Test Dialog</DialogTitle>
            <p>Dialog content</p>
          </DialogContent>
        </Dialog>
      </I18nextProvider>,
    );
    const results = await axe(baseElement);
    expect(results).toHaveNoViolations();
  });
});
