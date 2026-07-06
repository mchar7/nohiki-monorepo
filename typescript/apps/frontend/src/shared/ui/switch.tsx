import { Root, Thumb } from '@radix-ui/react-switch';
import type { JSX } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';

function Switch({ className, ref, ...props }: React.ComponentProps<typeof Root>): JSX.Element {
  return (
    <Root
      className={cn(
        'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-60 data-[state=checked]:bg-primary data-[state=unchecked]:bg-input',
        className,
      )}
      {...props}
      ref={ref}
    >
      <Thumb
        className={cn(
          'pointer-events-none block size-4 rounded-full bg-background shadow-lg ring-0 transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0',
        )}
      />
    </Root>
  );
}

export { Switch };
