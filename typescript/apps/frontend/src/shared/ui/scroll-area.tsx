import {
  Corner,
  Root,
  ScrollAreaScrollbar,
  ScrollAreaThumb,
  Viewport,
} from '@radix-ui/react-scroll-area';
import type { JSX } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';

function ScrollArea({
  className,
  children,
  ref,
  ...props
}: React.ComponentProps<typeof Root>): JSX.Element {
  return (
    <Root ref={ref} className={cn('relative overflow-hidden', className)} {...props}>
      <Viewport className="h-full w-full rounded-[inherit]">{children}</Viewport>
      <ScrollBar />
      <Corner />
    </Root>
  );
}

function ScrollBar({
  className,
  orientation = 'vertical',
  ref,
  ...props
}: React.ComponentProps<typeof ScrollAreaScrollbar>): JSX.Element {
  return (
    <ScrollAreaScrollbar
      ref={ref}
      orientation={orientation}
      className={cn(
        'flex touch-none select-none transition-colors',
        orientation === 'vertical' && 'h-full w-2.5 border-l border-l-transparent p-px',
        orientation === 'horizontal' && 'h-2.5 flex-col border-t border-t-transparent p-px',
        className,
      )}
      {...props}
    >
      <ScrollAreaThumb className="relative flex-1 rounded-full bg-border" />
    </ScrollAreaScrollbar>
  );
}

export { ScrollArea };
