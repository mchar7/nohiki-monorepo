import { Anchor, Content, Portal, Root, Trigger } from '@radix-ui/react-popover';
import type { JSX } from 'react';

import { cn } from '@/shared/lib/utils/utils.ts';

const Popover: typeof Root = Root;

const PopoverTrigger: typeof Trigger = Trigger;

export const PopoverAnchor: typeof Anchor = Anchor;

function PopoverContent({
  className,
  align = 'center',
  sideOffset = 4,
  ref,
  ...props
}: React.ComponentProps<typeof Content>): JSX.Element {
  return (
    <Portal>
      <Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        className={cn(
          'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 z-50 w-72 origin-[--radix-popover-content-transform-origin] rounded-md border bg-popover p-4 text-popover-foreground shadow-md outline-none data-[state=closed]:animate-out data-[state=open]:animate-in',
          className,
        )}
        {...props}
      />
    </Portal>
  );
}

export { Popover, PopoverContent, PopoverTrigger };
