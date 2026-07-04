import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import type { UserResponse } from '@/shared/api';
import { i18n } from '@/test/setup.ts';
import { ProfileSection } from './ProfileSection.tsx';

const mockUpdateAccount = vi.hoisted(() => vi.fn().mockResolvedValue({}));

vi.mock('../api/index.ts', () => ({
  useUpdateAccount: () => ({ mutateAsync: mockUpdateAccount, isPending: false }),
}));
vi.mock('@/shared/lib/index.ts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/index.ts')>();
  return {
    ...actual,
    extractErrorReason: () => undefined,
    useUnsavedChanges: () => ({ status: 'idle', proceed: undefined, reset: undefined }),
  };
});
vi.mock('@/shared/ui/unsaved-changes-dialog.tsx', () => ({ UnsavedChangesDialog: () => null }));
vi.mock('./AvatarUploadSection.tsx', () => ({ AvatarUploadSection: () => null }));

const ACCOUNT: UserResponse = {
  id: 'acct-1',
  email: 'a@b.com',
  first_name: null,
  last_name: null,
  display_name: 'Existing Name',
  is_active: true,
  created_at: '2025-01-01T00:00:00.000Z',
  updated_at: '2025-01-01T00:00:00.000Z',
};

function renderProfile(account: UserResponse = ACCOUNT): void {
  render(
    <I18nextProvider i18n={i18n}>
      <ProfileSection account={account} />
    </I18nextProvider>,
  );
}

describe('ProfileSection display name contract', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('loads a legacy null display name but refuses to save until corrected', async () => {
    const user = userEvent.setup();
    renderProfile({ ...ACCOUNT, display_name: null });

    expect(screen.getByLabelText(/display name/iu)).toHaveValue('');
    await user.click(screen.getByRole('button', { name: /save changes/iu }));

    expect(screen.getByLabelText(/display name/iu)).toBeInvalid();
    expect(mockUpdateAccount).not.toHaveBeenCalled();
  });

  test.each([
    '',
    '   ',
    '\u00a0\u2003',
  ])('rejects explicit blank display name %j', async (value) => {
    const user = userEvent.setup();
    renderProfile();

    fireEvent.change(screen.getByLabelText(/display name/iu), { target: { value } });
    await user.click(screen.getByRole('button', { name: /save changes/iu }));

    expect(mockUpdateAccount).not.toHaveBeenCalled();
  });

  test('normalizes display name while first and last names remain optional', async () => {
    const user = userEvent.setup();
    renderProfile();

    fireEvent.change(screen.getByLabelText(/display name/iu), {
      target: { value: '  Élodie\u3000李  O’Connor-Søndergaard  ' },
    });
    expect(screen.getByLabelText(/first name/iu)).toHaveValue('');
    expect(screen.getByLabelText(/last name/iu)).toHaveValue('');
    await user.click(screen.getByRole('button', { name: /save changes/iu }));

    await waitFor(() => {
      expect(mockUpdateAccount).toHaveBeenCalledWith({
        body: {
          display_name: 'Élodie 李 O’Connor-Søndergaard',
          first_name: null,
          last_name: null,
        },
      });
    });
  });
});
