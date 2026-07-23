import { config } from '@shared/config/index.ts';
import { Button } from '@shared/ui/button.tsx';
import { Tooltip, TooltipContent, TooltipTrigger } from '@shared/ui/tooltip.tsx';
import type { JSX } from 'react';

interface ConditionalTooltipButtonProps extends React.ComponentProps<typeof Button> {
  showTooltip: boolean;
  tooltip: string;
  children: React.ReactNode;
}

export function ConditionalTooltipButton({
  showTooltip,
  tooltip,
  children,
  ...buttonProps
}: ConditionalTooltipButtonProps): JSX.Element {
  return showTooltip ? (
    <Tooltip delayDuration={config.ui.toastDuration}>
      <TooltipTrigger asChild={true}>
        <Button {...buttonProps}>{children}</Button>
      </TooltipTrigger>
      <TooltipContent>
        <p>{tooltip}</p>
      </TooltipContent>
    </Tooltip>
  ) : (
    <Button {...buttonProps}>{children}</Button>
  );
}
