import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { WizardState } from '../../lib/wizardReducer.ts';

const mocks = vi.hoisted(() => ({
  useAccount: vi.fn(),
  useProfiles: vi.fn(),
  useMyCorrelations: vi.fn(),
  useTemplateFamilies: vi.fn(),
}));

vi.mock('@features/account/index.ts', () => ({ useAccount: mocks.useAccount }));
vi.mock('@features/profile-management/index.ts', () => ({ useProfiles: mocks.useProfiles }));
vi.mock('@features/job-matching/index.ts', () => ({ useMyCorrelations: mocks.useMyCorrelations }));
vi.mock('@features/omakase/document-builder', () => ({
  useTemplateFamilies: mocks.useTemplateFamilies,
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import { ReviewStep } from './ReviewStep.tsx';

const BASE_STATE: WizardState = {
  step: 4,
  docType: 'resume',
  profileId: 'profile-1',
  matchId: null,
  templateId: 'template-version-1',
  formData: {},
};

function arrange(displayName: string | null): void {
  mocks.useAccount.mockReturnValue({
    data: {
      id: 'user-1',
      email: 'person@example.com',
      display_name: displayName,
      first_name: null,
      last_name: null,
    },
  });
  mocks.useProfiles.mockReturnValue({
    data: { items: [{ id: 'profile-1', pref_name: 'Engineer' }] },
  });
  mocks.useMyCorrelations.mockReturnValue({ data: { items: [] } });
  mocks.useTemplateFamilies.mockReturnValue({
    data: {
      items: [
        {
          name: 'Resume',
          latest_version: {
            id: 'template-version-1',
            content_schema: {
              type: 'object',
              properties: { full_name: { type: 'string', title: 'Full name' } },
              required: ['full_name'],
            },
          },
        },
      ],
    },
  });
}

describe('ReviewStep name preflight', () => {
  beforeEach(() => vi.clearAllMocks());

  test.each([null, '   '])(
    'blocks generation with localized profile guidance when display name is %s',
    async (displayName) => {
      const user = userEvent.setup();
      const onGenerate = vi.fn();
      arrange(displayName);

      render(
        <ReviewStep
          state={BASE_STATE}
          onFormDataChange={vi.fn()}
          onGenerate={onGenerate}
          isGenerating={false}
        />,
      );
      await user.click(screen.getByRole('button', { name: 'wizard.navigation.generate' }));

      expect(onGenerate).not.toHaveBeenCalled();
      expect(screen.getByText('wizard.review.nameRequired')).toBeInTheDocument();
    },
  );

  test('maps display name to full_name and permits generation', async () => {
    const user = userEvent.setup();
    const onFormDataChange = vi.fn();
    const onGenerate = vi.fn();
    arrange('Zoë O’Neil-Sato');

    const { rerender } = render(
      <ReviewStep
        state={BASE_STATE}
        onFormDataChange={onFormDataChange}
        onGenerate={onGenerate}
        isGenerating={false}
      />,
    );

    await waitFor(() =>
      expect(onFormDataChange).toHaveBeenCalledWith({ full_name: 'Zoë O’Neil-Sato' }),
    );
    rerender(
      <ReviewStep
        state={{ ...BASE_STATE, formData: { full_name: 'Zoë O’Neil-Sato' } }}
        onFormDataChange={onFormDataChange}
        onGenerate={onGenerate}
        isGenerating={false}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'wizard.navigation.generate' }));

    expect(onGenerate).toHaveBeenCalledOnce();
    expect(screen.queryByText('wizard.review.nameRequired')).not.toBeInTheDocument();
  });
});
