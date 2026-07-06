import { Indicator, Root } from '@radix-ui/react-progress';

/** Full percentage value used to compute translateX offset for the progress indicator */
const FULL_PERCENT: number = 100;

import type { JSX } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';

function Progress({
  className,
  value,
  ref,
  ...props
}: React.ComponentProps<typeof Root>): JSX.Element {
  return (
    <Root
      ref={ref}
      className={cn('relative h-2 w-full overflow-hidden rounded-full bg-primary/20', className)}
      {...props}
    >
      <Indicator
        className="h-full w-full flex-1 bg-primary transition-all"
        style={{ transform: `translateX(-${FULL_PERCENT - (value ?? 0)}%)` }}
      />
    </Root>
  );
}

export { Progress };
