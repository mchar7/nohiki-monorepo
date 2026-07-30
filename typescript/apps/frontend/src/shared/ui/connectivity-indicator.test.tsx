import type { RenderResult } from '@testing-library/react';
import { render, screen } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';
import { describe, expect } from 'vitest';
import {
  ConnectivityContext,
  type ConnectivityContextValue,
} from '@/shared/lib/contexts/ConnectivityContextModel.ts';
import { i18n } from '@/test/i18n-setup.ts';
import { ConnectivityIndicator } from './connectivity-indicator.tsx';

const LAST_CHECKED_AT = 1_700_000_000_000;
const defaultConnectivity: ConnectivityContextValue = {
  status: 'online',
  isBackendAvailable: true,
  isOnline: true,
  isOffline: false,
  isChecking: false,
  isDegraded: false,
  lastChecked: new Date(LAST_CHECKED_AT),
  lastCheckedAt: LAST_CHECKED_AT,
  failureCount: 0,
  timeSinceDisconnect: 0,
  hasChecked: true,
  forceCheck: () => Promise.resolve(true),
  checkNow: () => Promise.resolve(true),
};

function renderIndicator(overrides: Partial<ConnectivityContextValue> = {}): RenderResult {
  return render(
    <ConnectivityContext.Provider value={{ ...defaultConnectivity, ...overrides }}>
      <I18nextProvider i18n={i18n}>
        <ConnectivityIndicator />
      </I18nextProvider>
    </ConnectivityContext.Provider>,
  );
}

describe('ConnectivityIndicator', () => {
  test('renders a button', () => {
    renderIndicator();
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  test('shows connected status when backend is available', () => {
    renderIndicator({ isBackendAvailable: true, lastCheckedAt: LAST_CHECKED_AT });
    expect(screen.getByRole('button', { name: 'Connected' })).toBeInTheDocument();
  });

  test('shows unknown status when lastCheckedAt is null', () => {
    renderIndicator({ isChecking: false, lastChecked: null, lastCheckedAt: null });
    expect(screen.getByRole('button', { name: 'Connecting...' })).toBeInTheDocument();
  });

  test('shows checking status when isChecking is true', () => {
    renderIndicator({ isChecking: true, status: 'checking' });
    expect(screen.getByRole('button', { name: 'Checking connection...' })).toBeInTheDocument();
  });

  test('shows disconnected status when backend is unavailable', () => {
    renderIndicator({
      status: 'offline',
      isBackendAvailable: false,
      isOnline: false,
      isOffline: true,
    });
    expect(screen.getByRole('button', { name: 'Disconnected' })).toBeInTheDocument();
  });
});
