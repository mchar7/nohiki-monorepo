import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import type { ScoreFeedbackType } from '@/shared/api';
import { i18n } from '@/test/i18n-setup.ts';
import { FeedbackSection } from './FeedbackSection.tsx';

interface RenderFeedbackOptions {
  readonly onScoreFeedback?: (type: ScoreFeedbackType) => Promise<void>;
  readonly isSubmitting?: boolean;
}

function renderFeedback({
  onScoreFeedback = vi.fn(),
  isSubmitting = false,
}: RenderFeedbackOptions = {}): void {
  render(
    <I18nextProvider i18n={i18n}>
      <FeedbackSection
        currentScore={85}
        onScoreFeedback={onScoreFeedback}
        onScoreAdjust={vi.fn()}
        isSubmitting={isSubmitting}
      />
    </I18nextProvider>,
  );
}

describe('FeedbackSection one-click feedback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test.each([
    ['Good match', 'GOOD'],
    ['Score too high', 'TOO_HIGH'],
    ['Score too low', 'TOO_LOW'],
  ] as const)('submits %s immediately with the exact feedback value', async (label, value) => {
    const user = userEvent.setup();
    const onScoreFeedback = vi.fn().mockResolvedValue(undefined);
    renderFeedback({ onScoreFeedback });

    await user.click(screen.getByRole('radio', { name: label }));

    expect(onScoreFeedback).toHaveBeenCalledOnce();
    expect(onScoreFeedback).toHaveBeenCalledWith(value);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Submit Feedback' })).not.toBeInTheDocument();
  });

  test('keyboard activation submits once and does not require optional details', async () => {
    const user = userEvent.setup();
    const onScoreFeedback = vi.fn().mockResolvedValue(undefined);
    renderFeedback({ onScoreFeedback });

    const good = screen.getByRole('radio', { name: 'Good match' });
    good.focus();
    await user.keyboard('{Enter}');

    expect(onScoreFeedback).toHaveBeenCalledOnce();
    expect(onScoreFeedback).toHaveBeenCalledWith('GOOD');
    expect(screen.getByRole('button', { name: 'Adjust Score' })).toBeInTheDocument();
  });

  test('keeps the selected state visible and changes it with one click', async () => {
    const user = userEvent.setup();
    const onScoreFeedback = vi.fn().mockResolvedValue(undefined);
    renderFeedback({ onScoreFeedback });

    const good = screen.getByRole('radio', { name: 'Good match' });
    const tooHigh = screen.getByRole('radio', { name: 'Score too high' });
    await user.click(good);
    expect(good).toBeChecked();

    await user.click(tooHigh);
    expect(good).not.toBeChecked();
    expect(tooHigh).toBeChecked();
    expect(onScoreFeedback).toHaveBeenNthCalledWith(1, 'GOOD');
    expect(onScoreFeedback).toHaveBeenNthCalledWith(2, 'TOO_HIGH');
  });

  test('rolls back a failed selection and announces the localized error', async () => {
    const user = userEvent.setup();
    const onScoreFeedback = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('temporarily unavailable'));
    renderFeedback({ onScoreFeedback });

    const good = screen.getByRole('radio', { name: 'Good match' });
    const tooLow = screen.getByRole('radio', { name: 'Score too low' });
    await user.click(good);
    await user.click(tooLow);

    await waitFor(() => expect(good).toBeChecked());
    expect(tooLow).not.toBeChecked();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Failed to submit feedback. Please try again.',
    );
  });

  test('suppresses duplicate rapid clicks while the mutation is pending', async () => {
    const user = userEvent.setup();
    let resolveMutation: (() => void) | undefined;
    const onScoreFeedback = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveMutation = resolve;
        }),
    );
    renderFeedback({ onScoreFeedback });

    const good = screen.getByRole('radio', { name: 'Good match' });
    await user.dblClick(good);

    expect(onScoreFeedback).toHaveBeenCalledOnce();
    resolveMutation?.();
    await waitFor(() => expect(good).toBeChecked());
  });
});
