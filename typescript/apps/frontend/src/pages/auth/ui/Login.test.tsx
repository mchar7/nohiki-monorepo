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

import { Login } from './Login.tsx';

const mockNavigate = vi.fn<ReturnType<typeof useNavigate>>() as ReturnType<typeof useNavigate>;

describe('Login', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useNavigate).mockReturnValue(mockNavigate);
    mockNavigate.mockResolvedValue(undefined);
  });

  test('renders page wrapper with correct classes', () => {
    const { container } = render(<Login />);
    expect(container.firstChild).toHaveClass('relative', 'min-h-svh');
  });

  test('renders AuthPage in login mode', () => {
    render(<Login />);
    expect(screen.getByTestId('auth-page-login')).toBeInTheDocument();
  });

  test('navigates to home with replace on success when no returnUrl', async () => {
    const user = userEvent.setup();
    render(<Login />);
    await user.click(screen.getByRole('button', { name: 'Complete Auth' }));
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/', replace: true });
  });

  test('contains a rejected post-login navigation promise', async () => {
    mockNavigate.mockRejectedValue(new Error('router disposed'));
    const user = userEvent.setup();
    render(<Login />);

    await user.click(screen.getByRole('button', { name: 'Complete Auth' }));

    expect(mockNavigate).toHaveBeenCalledWith({ to: '/', replace: true });
  });

  test('navigates to returnUrl with href on success when returnUrl is provided', async () => {
    const user = userEvent.setup();
    render(<Login returnUrl="/dashboard?tab=jobs" />);
    await user.click(screen.getByRole('button', { name: 'Complete Auth' }));
    expect(mockNavigate).toHaveBeenCalledWith({ href: '/dashboard?tab=jobs', replace: true });
  });

  test('navigates to home when returnUrl is empty string', async () => {
    const user = userEvent.setup();
    render(<Login returnUrl="" />);
    await user.click(screen.getByRole('button', { name: 'Complete Auth' }));
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/', replace: true });
  });

  test.each([
    '//attacker.example/steal',
    '/\\attacker.example/steal',
  ])('navigates home instead of following unsafe returnUrl %s', async (returnUrl) => {
    const user = userEvent.setup();
    render(<Login returnUrl={returnUrl} />);

    await user.click(screen.getByRole('button', { name: 'Complete Auth' }));

    expect(mockNavigate).toHaveBeenCalledWith({ to: '/', replace: true });
    expect(mockNavigate).not.toHaveBeenCalledWith(
      expect.objectContaining({ href: expect.any(String) }),
    );
  });
});
