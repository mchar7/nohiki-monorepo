import { Indicator, Root } from '@radix-ui/react-checkbox';
import { cn } from '@shared/lib/index.ts';
import { CheckIcon } from 'lucide-react';
import type * as React from 'react';
import type { JSX } from 'react';

function Checkbox({ className, ...props }: React.ComponentProps<typeof Root>): JSX.Element {
  return (
    <Root
      data-slot="checkbox"
      className={cn(
        'peer size-4 shrink-0 rounded-[4px] border border-input shadow-xs outline-none transition-shadow focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-destructive aria-invalid:ring-destructive/20 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground dark:bg-input/30 dark:data-[state=checked]:bg-primary dark:aria-invalid:ring-destructive/40',
        className,
      )}
      {...props}
    >
      <Indicator
        data-slot="checkbox-indicator"
        className="flex items-center justify-center text-current transition-none"
      >
        <CheckIcon className="size-3.5" />
      </Indicator>
    </Root>
  );
}

export { Checkbox };
