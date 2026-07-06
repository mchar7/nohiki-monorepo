import { Loader2 } from 'lucide-react';
import type { JSX } from 'react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useConnectivitySafe } from '@/shared/lib/contexts/index.ts';
import { cn } from '@/shared/lib/utils/utils.ts';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './tooltip.tsx';

type ConnectionStatus = 'connected' | 'checking' | 'disconnected' | 'unknown';

const SPINNER_DELAY_MS: number = 2000;
/** Minimum disconnect duration before showing the retry button (ms) */
const MIN_DISCONNECT_BEFORE_RETRY_MS: number = 5000;

function useDelayedSpinner(isChecking: boolean): boolean {
  const [showSpinner, setShowSpinner] = useState(false);
  const spinnerTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isChecking) {
      spinnerTimeoutRef.current = setTimeout(() => {
        setShowSpinner(true);
      }, SPINNER_DELAY_MS);
    } else {
      if (spinnerTimeoutRef.current) {
        clearTimeout(spinnerTimeoutRef.current);
        spinnerTimeoutRef.current = null;
      }
      setShowSpinner(false);
    }

    return () => {
      if (spinnerTimeoutRef.current) {
        clearTimeout(spinnerTimeoutRef.current);
      }
    };
  }, [isChecking]);

  return showSpinner;
}

function getConnectionStatus(
  lastCheckedAt: number | null,
  isChecking: boolean,
  isBackendAvailable: boolean,
): ConnectionStatus {
  if (lastCheckedAt === null && !isChecking) {
    return 'unknown';
  }
  if (isChecking) {
    return 'checking';
  }
  if (isBackendAvailable) {
    return 'connected';
  }
  return 'disconnected';
}

function StatusDot({ status }: { readonly status: ConnectionStatus }): JSX.Element {
  return (
    <span
      className={cn(
        'h-2.5 w-2.5 rounded-full transition-all duration-300',
        status === 'connected' && 'bg-success shadow-glow-success',
        status === 'checking' && 'animate-pulse-fast bg-warning shadow-glow-warning',
        status === 'unknown' && 'bg-warning shadow-glow-warning',
        status === 'disconnected' && 'bg-destructive shadow-glow-destructive',
      )}
    />
  );
}

function resolveStatusText(
  t: (key: string, opts?: Record<string, unknown>) => string,
  status: ConnectionStatus,
  isChecking: boolean,
  isBackendAvailable: boolean,
): string {
  if (status === 'unknown') {
    return t('connectivity.unknown');
  }
  if (isChecking) {
    return t('connectivity.checking');
  }
  return isBackendAvailable ? t('connectivity.connected') : t('connectivity.disconnected');
}

interface TooltipBodyProps {
  readonly statusText: string;
  readonly isDisconnected: boolean;
  readonly lastCheckText: string;
  readonly canRetry: boolean;
}

function TooltipBody({
  statusText,
  isDisconnected,
  lastCheckText,
  canRetry,
}: TooltipBodyProps): JSX.Element {
  const { t } = useTranslation('common');
  return (
    <TooltipContent side="bottom" className="max-w-60 text-sm">
      <p className="font-medium">{statusText}</p>
      {isDisconnected ? (
        <p className="text-muted-foreground text-xs">{t('connectivity.disconnectedDetail')}</p>
      ) : null}
      {lastCheckText ? <p className="text-muted-foreground text-xs">{lastCheckText}</p> : null}
      {canRetry ? (
        <p className="text-muted-foreground text-xs">{t('connectivity.clickToRetry')}</p>
      ) : null}
    </TooltipContent>
  );
}

export function ConnectivityIndicator(): JSX.Element {
  const { t } = useTranslation('common');
  const {
    isBackendAvailable,
    isOffline,
    isChecking,
    lastCheckedAt,
    checkNow,
    timeSinceDisconnect,
  } = useConnectivitySafe();

  const [canRetry, setCanRetry] = useState(false);
  const showSpinner = useDelayedSpinner(isChecking);

  useEffect(() => {
    setCanRetry(isOffline && timeSinceDisconnect >= MIN_DISCONNECT_BEFORE_RETRY_MS && !isChecking);
  }, [isOffline, timeSinceDisconnect, isChecking]);

  const status = getConnectionStatus(lastCheckedAt, isChecking, isBackendAvailable);
  const statusText = resolveStatusText(t, status, isChecking, isBackendAvailable);
  const lastCheckText = lastCheckedAt
    ? t('connectivity.lastChecked', { time: new Date(lastCheckedAt).toLocaleTimeString() })
    : '';

  return (
    <TooltipProvider>
      <Tooltip delayDuration={200}>
        <TooltipTrigger asChild={true}>
          <button
            type="button"
            onClick={canRetry ? checkNow : undefined}
            className={cn(
              'flex h-8 items-center justify-center rounded-md px-2 transition-colors',
              canRetry && 'cursor-pointer hover:bg-muted/50',
              !canRetry && 'cursor-default',
            )}
            aria-label={statusText}
          >
            {showSpinner ? (
              <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
            ) : (
              <StatusDot status={status} />
            )}
          </button>
        </TooltipTrigger>
        <TooltipBody
          statusText={statusText}
          isDisconnected={status === 'disconnected'}
          lastCheckText={lastCheckText}
          canRetry={canRetry}
        />
      </Tooltip>
    </TooltipProvider>
  );
}
