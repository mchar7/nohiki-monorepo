import { Fallback, Image, Root } from '@radix-ui/react-avatar';
import { cn } from '@shared/lib/index.ts';
import type * as React from 'react';
import type { JSX } from 'react';

function Avatar({ className, ...props }: React.ComponentProps<typeof Root>): JSX.Element {
  return (
    <Root
      data-slot="avatar"
      className={cn('relative flex size-8 shrink-0 overflow-hidden rounded-full', className)}
      {...props}
    />
  );
}

export function AvatarImage({
  className,
  ...props
}: React.ComponentProps<typeof Image>): JSX.Element {
  return (
    <Image
      data-slot="avatar-image"
      className={cn('aspect-square size-full', className)}
      {...props}
    />
  );
}

function AvatarFallback({
  className,
  ...props
}: React.ComponentProps<typeof Fallback>): JSX.Element {
  return (
    <Fallback
      data-slot="avatar-fallback"
      className={cn('flex size-full items-center justify-center rounded-full bg-muted', className)}
      {...props}
    />
  );
}

export { Avatar, AvatarFallback };
