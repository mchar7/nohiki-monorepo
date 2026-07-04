import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, test, vi } from 'vitest';

import type { UserResponse } from '@/shared/api';
import { AvatarUploadSection } from './AvatarUploadSection.tsx';

vi.mock('@/shared/ui/avatar.tsx', () => ({
  Avatar: ({ children }: { readonly children: ReactNode }) => <div>{children}</div>,
  AvatarFallback: ({ children }: { readonly children: ReactNode }) => (
    <span data-testid="avatar-fallback">{children}</span>
  ),
}));
vi.mock('@/shared/ui/card.tsx', () => ({
  Card: ({ children }: { readonly children: ReactNode }) => <div>{children}</div>,
  CardContent: ({ children }: { readonly children: ReactNode }) => <div>{children}</div>,
  CardDescription: ({ children }: { readonly children: ReactNode }) => <div>{children}</div>,
  CardHeader: ({ children }: { readonly children: ReactNode }) => <div>{children}</div>,
  CardTitle: ({ children }: { readonly children: ReactNode }) => <div>{children}</div>,
}));

const BASE_ACCOUNT: UserResponse = {
  id: 'acct-1',
  email: 'fallback@example.com',
  first_name: 'Structured',
  last_name: 'Name',
  display_name: 'Preferred',
  is_active: true,
  created_at: '2025-01-01T00:00:00.000Z',
  updated_at: '2025-01-01T00:00:00.000Z',
};

function renderFallback(overrides: Partial<UserResponse> = {}): HTMLElement {
  render(<AvatarUploadSection account={{ ...BASE_ACCOUNT, ...overrides }} />);
  return screen.getByTestId('avatar-fallback');
}

describe('AvatarUploadSection fallback priority', () => {
  test('uses display name before structured names and email', () => {
    expect(renderFallback()).toHaveTextContent('P');
  });

  test('uses first and last names when display name is absent', () => {
    expect(renderFallback({ display_name: null })).toHaveTextContent('SN');
  });

  test.each([
    [{ first_name: '李', last_name: null }, '李'],
    [{ first_name: null, last_name: 'O’Connor' }, 'O'],
  ] satisfies ReadonlyArray<
    readonly [Partial<UserResponse>, string]
  >)('supports either optional structured name %#', (overrides, expected) => {
    expect(renderFallback({ display_name: null, ...overrides })).toHaveTextContent(expected);
  });

  test('uses email only when no display or structured name is available', () => {
    expect(
      renderFallback({ display_name: null, first_name: null, last_name: null }),
    ).toHaveTextContent('F');
  });
});
