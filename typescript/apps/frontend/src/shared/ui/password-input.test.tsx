import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { describe, expect } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import { PasswordInput } from './password-input.tsx';

const PASSWORD_LABEL = 'Account password';

describe('PasswordInput keyboard behavior', () => {
  test('toggles visibility with Space and Enter without moving focus from the control', async () => {
    const user = userEvent.setup();
    render(
      <I18nextProvider i18n={i18n}>
        <PasswordInput
          aria-label={PASSWORD_LABEL}
          value="correct horse battery staple"
          readOnly={true}
        />
      </I18nextProvider>,
    );
    const input = screen.getByLabelText(PASSWORD_LABEL);
    const toggle = screen.getByRole('button', { name: /show password/iu });
    input.focus();

    await user.tab();
    expect(toggle).toHaveFocus();
    await user.keyboard(' ');

    expect(input).toHaveAttribute('type', 'text');
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(toggle).toHaveAccessibleName(/hide password/iu);
    expect(toggle).toHaveFocus();

    await user.keyboard('{Enter}');

    expect(input).toHaveAttribute('type', 'password');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(toggle).toHaveAccessibleName(/show password/iu);
    expect(toggle).toHaveFocus();
  });
});
