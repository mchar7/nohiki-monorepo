import { cn } from '@shared/lib/index.ts';
import { cva, type VariantProps } from 'class-variance-authority';
import type * as React from 'react';
import type { JSX } from 'react';

const alertVariants = cva(
  'relative w-full rounded-xl border px-4 py-4 text-sm grid has-[>svg]:grid-cols-[calc(var(--spacing)*5)_1fr] grid-cols-[0_1fr] has-[>svg]:gap-x-3 gap-y-1 items-start [&>svg]:size-5 [&>svg]:translate-y-0.5',
  {
    variants: {
      variant: {
        default: 'bg-card text-card-foreground border-border/50 [&>svg]:text-muted-foreground',
        destructive:
          'bg-destructive/5 border-destructive/20 text-destructive [&>svg]:text-destructive *:data-[slot=alert-description]:text-destructive/80',
        warning:
          'bg-warning/10 border-warning/30 text-foreground [&>svg]:text-warning *:data-[slot=alert-description]:text-muted-foreground',
        success:
          'bg-success/5 border-success/20 text-success-foreground [&>svg]:text-success *:data-[slot=alert-description]:text-success-foreground/80',
        info: 'bg-primary/5 border-primary/20 text-foreground [&>svg]:text-primary *:data-[slot=alert-description]:text-muted-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

function Alert({
  className,
  variant,
  ...props
}: React.ComponentProps<'div'> & VariantProps<typeof alertVariants>): JSX.Element {
  return (
    <div
      data-slot="alert"
      role="alert"
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  );
}

function AlertTitle({ className, ...props }: React.ComponentProps<'div'>): JSX.Element {
  return (
    <div
      data-slot="alert-title"
      className={cn('col-start-2 min-h-5 font-semibold tracking-tight', className)}
      {...props}
    />
  );
}

function AlertDescription({ className, ...props }: React.ComponentProps<'div'>): JSX.Element {
  return (
    <div
      data-slot="alert-description"
      className={cn(
        'col-start-2 grid justify-items-start gap-1 text-sm leading-relaxed [&_p]:leading-relaxed',
        className,
      )}
      {...props}
    />
  );
}

export { Alert, AlertDescription, AlertTitle };
