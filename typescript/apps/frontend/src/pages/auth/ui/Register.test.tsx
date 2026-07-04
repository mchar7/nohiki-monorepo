import { useNavigate } from '@tanstack/react-router';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, vi } from 'vitest';

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>();
  return { ...actual, useNavigate: vi.fn() };
});

vi.mock('./AuthListingsCanvas.tsx', () => ({
  AuthListingsCanvas: () => null,
}));

vi.mock('@/features/auth', () => ({
  AuthPage: vi.fn(
    ({
      onSuccess,
      defaultMode,
    }: {
      readonly onSuccess: () => void;
      readonly defaultMode: string;
    }) => (
      <button type="button" data-testid={`auth-page-${defaultMode}`} onClick={onSuccess}>
        Complete Auth
      </button>
    ),
  ),
}));

import { Register } from './Register.tsx';

const mockNavigate = vi.fn<ReturnType<typeof useNavigate>>() as ReturnType<typeof useNavigate>;

describe('Register', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useNavigate).mockReturnValue(mockNavigate);
    mockNavigate.mockResolvedValue(undefined);
  });

  test('renders page wrapper with correct classes', () => {
    const { container } = render(<Register />);
    expect(container.firstChild).toHaveClass('relative', 'min-h-svh');
  });

  test('renders AuthPage in register mode', () => {
    render(<Register />);
    expect(screen.getByTestId('auth-page-register')).toBeInTheDocument();
  });

  test('navigates to home with replace on success', async () => {
    const user = userEvent.setup();
    render(<Register />);
    await user.click(screen.getByRole('button', { name: 'Complete Auth' }));
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/', replace: true });
  });

  test('contains a rejected post-registration navigation promise', async () => {
    mockNavigate.mockRejectedValue(new Error('router disposed'));
    const user = userEvent.setup();
    render(<Register />);

    await user.click(screen.getByRole('button', { name: 'Complete Auth' }));

    expect(mockNavigate).toHaveBeenCalledWith({ to: '/', replace: true });
  });
});
