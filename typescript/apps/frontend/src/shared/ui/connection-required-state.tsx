import { RefreshCw, WifiOff } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';

interface ConnectionRequiredStateProps {
  /** Custom title override */
  readonly title?: string;
  /** Custom description override */
  readonly description?: string;
  /** Size variant */
  readonly size?: 'sm' | 'md' | 'lg';
  /** Additional hint text */
  readonly hint?: string;
  /** Callback invoked when the user clicks the Retry button */
  readonly onRetry?: () => void;
}

/**
 * A consistent disconnected/offline state component used throughout the app.
 * Shows the WifiOff icon with appropriate messaging.
 *
 * Use this when:
 * - Backend is confirmed offline (hasChecked && isOffline)
 * - A feature requires backend connectivity
 *
 * Do NOT use when:
 * - Initial load hasn't completed yet (hasChecked === false)
 * - Actively checking connectivity (isChecking)
 */
export function ConnectionRequiredState({
  title,
  description,
  size = 'md',
  hint,
  onRetry,
}: ConnectionRequiredStateProps): JSX.Element {
  const { t } = useTranslation('common');

  const sizeClasses = {
    sm: {
      container: 'gap-3 py-6',
      wrapper: 'size-10',
      icon: 'size-5',
      title: 'text-sm font-medium',
      description: 'text-xs',
      hint: 'text-xs',
    },
    md: {
      container: 'gap-3 py-6',
      wrapper: 'size-12',
      icon: 'size-6',
      title: 'text-base font-medium',
      description: 'text-sm',
      hint: 'text-xs',
    },
    lg: {
      container: 'gap-4 py-8',
      wrapper: 'h-14 w-14',
      icon: 'size-7',
      title: 'text-lg font-semibold',
      description: 'text-base',
      hint: 'text-sm',
    },
  };

  const classes = sizeClasses[size];

  return (
    <div
      className={`flex h-full flex-col items-center justify-center text-center ${classes.container}`}
    >
      <div className={`flex items-center justify-center rounded-full bg-muted ${classes.wrapper}`}>
        <WifiOff className={`${classes.icon} text-muted-foreground`} />
      </div>
      <div className="space-y-1">
        <p className={`${classes.title} text-muted-foreground`}>
          {title ?? t('connectivity.offline')}
        </p>
        <p className={`${classes.description} text-muted-foreground/70`}>
          {description ?? t('connectivity.offlineDescription')}
        </p>
      </div>
      {hint ? <p className={`${classes.hint} text-muted-foreground/60`}>{hint}</p> : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium text-muted-foreground text-xs ring-1 ring-border transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <RefreshCw className="size-3" aria-hidden="true" />
          {t('connectivity.retry')}
        </button>
      ) : null}
    </div>
  );
}
