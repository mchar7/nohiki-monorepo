import type { VariantProps } from 'class-variance-authority';
import type { ComponentProps, JSX } from 'react';
import { useTranslation } from 'react-i18next';
import { useConnectivitySafe } from '../lib/contexts/index.ts';
import { cn } from '../lib/utils/utils.ts';
import { Button, type buttonVariants } from './button.tsx';
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip.tsx';

type ButtonProps = ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

interface ConnectivityAwareButtonProps extends ButtonProps {
  /** Whether this button requires server connectivity */
  readonly requiresConnection?: boolean;
  /** Custom tooltip when disabled due to offline status */
  readonly offlineTooltip?: string;
  /** Whether to show visual offline indicator */
  readonly showOfflineIndicator?: boolean;
}

/**
 * Button that automatically disables when server connectivity is unavailable.
 * Shows a localized tooltip explaining why the button is disabled.
 */
export function ConnectivityAwareButton({
  requiresConnection = true,
  offlineTooltip,
  showOfflineIndicator = true,
  disabled: propDisabled,
  children,
  className,
  ...props
}: ConnectivityAwareButtonProps): JSX.Element {
  const { t } = useTranslation('common');
  const { isBackendAvailable } = useConnectivitySafe();

  const isOfflineDisabled = requiresConnection && !isBackendAvailable;
  const isDisabled = propDisabled || isOfflineDisabled;

  const tooltipContent = offlineTooltip ?? t('connectivity.requiresConnection');

  const button = (
    <Button
      disabled={isDisabled}
      className={cn(isOfflineDisabled && showOfflineIndicator && 'opacity-60', className)}
      {...(props as React.ComponentProps<typeof Button>)}
    >
      {children}
    </Button>
  );

  if (isOfflineDisabled) {
    return (
      <Tooltip>
        <TooltipTrigger asChild={true}>
          <span className="inline-flex cursor-not-allowed">{button}</span>
        </TooltipTrigger>
        <TooltipContent>
          <p>{tooltipContent}</p>
        </TooltipContent>
      </Tooltip>
    );
  }

  return button;
}
