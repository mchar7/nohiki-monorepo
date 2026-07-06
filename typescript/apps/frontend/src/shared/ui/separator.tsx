'use client';

import { Root } from '@radix-ui/react-separator';
import type { JSX } from 'react';

import { cn } from '@/shared/lib/utils/utils.ts';

function Separator({
  className,
  orientation = 'horizontal',
  decorative = true,
  ref,
  ...props
}: React.ComponentProps<typeof Root>): JSX.Element {
  return (
    <Root
      ref={ref}
      decorative={decorative}
      orientation={orientation}
      className={cn(
        'shrink-0 bg-border',
        orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px',
        className,
      )}
      {...props}
    />
  );
}

export { Separator };
