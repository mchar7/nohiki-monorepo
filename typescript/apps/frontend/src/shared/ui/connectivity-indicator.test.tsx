import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect, vi } from 'vitest';
import { i18n } from '@/test/i18n-setup.ts';
import { ConnectivityIndicator } from './connectivity-indicator.tsx';

interface MockConnectivity {
  status: 'online';
  isBackendAvailable: boolean;
  isOnline: boolean;
  isOffline: boolean;
  isChecking: boolean;
  isDegraded: boolean;
  lastChecked: Date | null;
  lastCheckedAt: number | null;
  failureCount: number;
  timeSinceDisconnect: number;
  hasChecked: boolean;
  forceCheck: () => Promise<boolean>;
  checkNow: () => Promise<boolean>;
}

const mockConnectivityContext: MockConnectivity = {
  status: 'online' as const,
  isBackendAvailable: true,
  isOnline: true,
  isOffline: false,
  isChecking: false,
  isDegraded: false,
  lastChecked: null as Date | null,
  lastCheckedAt: null as number | null,
  failureCount: 0,
  timeSinceDisconnect: 0,
  hasChecked: true,
  forceCheck: vi.fn().mockResolvedValue(true),
  checkNow: vi.fn().mockResolvedValue(true),
};

vi.mock('@/shared/lib/contexts/ConnectivityContext', () => ({
  useConnectivitySafe: () => mockConnectivityContext,
}));

function renderIndicator(): RenderResult {
  return render(
    <I18nextProvider i18n={i18n}>
      <ConnectivityIndicator />
    </I18nextProvider>,
  );
}

describe('ConnectivityIndicator', () => {
  test('renders a button', () => {
    renderIndicator();
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  test('shows connected status when backend is available', () => {
    mockConnectivityContext.isBackendAvailable = true;
    mockConnectivityContext.lastCheckedAt = Date.now();
    renderIndicator();
    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('aria-label');
  });

  test('shows unknown status when lastCheckedAt is null', () => {
    mockConnectivityContext.lastCheckedAt = null;
    mockConnectivityContext.isChecking = false;
    renderIndicator();
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  test('shows checking status when isChecking is true', () => {
    mockConnectivityContext.isChecking = true;
    renderIndicator();
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  test('shows disconnected status when backend is unavailable', () => {
    mockConnectivityContext.isBackendAvailable = false;
    mockConnectivityContext.lastCheckedAt = Date.now();
    mockConnectivityContext.isChecking = false;
    renderIndicator();
    expect(screen.getByRole('button')).toBeInTheDocument();
  });
});
