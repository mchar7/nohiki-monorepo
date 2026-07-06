import { Range, Root, Thumb, Track } from '@radix-ui/react-slider';
import type { JSX } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';

function Slider({ className, ref, ...props }: React.ComponentProps<typeof Root>): JSX.Element {
  return (
    <Root
      ref={ref}
      className={cn('relative flex w-full touch-none select-none items-center', className)}
      {...props}
    >
      <Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-primary/20">
        <Range className="absolute h-full bg-primary" />
      </Track>
      <Thumb className="block size-4 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50" />
    </Root>
  );
}

export { Slider };
