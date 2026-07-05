import { render, screen } from '@testing-library/react';
import type { JSX } from 'react';
import { describe, expect, vi } from 'vitest';
import { ConnectivityProvider, useConnectivityContext, useConnectivitySafe } from './index.ts';

vi.mock('../hooks/useConnectivity', () => ({
  useConnectivity: vi.fn().mockReturnValue({
    status: 'online',
    isBackendAvailable: true,
    isOnline: true,
    isOffline: false,
    isChecking: false,
    isDegraded: false,
    lastChecked: null,
    lastCheckedAt: null,
    failureCount: 0,
    timeSinceDisconnect: 0,
    hasChecked: true,
    forceCheck: vi.fn().mockResolvedValue(true),
    checkNow: vi.fn().mockResolvedValue(true),
  }),
}));

function TestConsumer(): JSX.Element {
  const context = useConnectivityContext();
  return (
    <div>
      <span data-testid="status">{context.status}</span>
      <span data-testid="isOnline">{context.isOnline.toString()}</span>
    </div>
  );
}

function SafeTestConsumer(): JSX.Element {
  const context = useConnectivitySafe();
  return (
    <div>
      <span data-testid="status">{context.status}</span>
      <span data-testid="isOnline">{context.isOnline.toString()}</span>
    </div>
  );
}

describe('ConnectivityContext', () => {
  describe('ConnectivityProvider', () => {
    test('provides connectivity context to children', () => {
      render(
        <ConnectivityProvider>
          <TestConsumer />
        </ConnectivityProvider>,
      );

      expect(screen.getByTestId('status')).toHaveTextContent('online');
      expect(screen.getByTestId('isOnline')).toHaveTextContent('true');
    });

    test('accepts custom healthEndpoint and checkInterval', () => {
      render(
        <ConnectivityProvider healthEndpoint="/custom-health" checkInterval={5000}>
          <TestConsumer />
        </ConnectivityProvider>,
      );

      expect(screen.getByTestId('status')).toHaveTextContent('online');
    });
  });

  describe('useConnectivityContext', () => {
    test('throws error when used outside provider', () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {
        /* suppress test output */
      });

      expect(() => {
        render(<TestConsumer />);
      }).toThrow('useConnectivityContext must be used within a ConnectivityProvider');

      consoleError.mockRestore();
    });
  });

  describe('useConnectivitySafe', () => {
    test('returns default values when used outside provider', () => {
      render(<SafeTestConsumer />);

      expect(screen.getByTestId('status')).toHaveTextContent('online');
      expect(screen.getByTestId('isOnline')).toHaveTextContent('true');
    });

    test('returns context values when used inside provider', () => {
      render(
        <ConnectivityProvider>
          <SafeTestConsumer />
        </ConnectivityProvider>,
      );

      expect(screen.getByTestId('status')).toHaveTextContent('online');
    });
  });
});
