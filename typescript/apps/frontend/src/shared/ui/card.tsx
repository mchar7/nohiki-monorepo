import type { JSX } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';

function Card({ className, ref, ...props }: React.ComponentProps<'div'>): JSX.Element {
  return (
    <div
      ref={ref}
      className={cn('rounded-xl border bg-card text-card-foreground shadow', className)}
      {...props}
    />
  );
}

function CardHeader({ className, ref, ...props }: React.ComponentProps<'div'>): JSX.Element {
  return <div ref={ref} className={cn('flex flex-col space-y-1.5 p-6', className)} {...props} />;
}

function CardTitle({ className, ref, ...props }: React.ComponentProps<'div'>): JSX.Element {
  return (
    <div
      ref={ref}
      className={cn('font-semibold leading-none tracking-tight', className)}
      {...props}
    />
  );
}

function CardDescription({ className, ref, ...props }: React.ComponentProps<'div'>): JSX.Element {
  return <div ref={ref} className={cn('text-muted-foreground text-sm', className)} {...props} />;
}

function CardContent({ className, ref, ...props }: React.ComponentProps<'div'>): JSX.Element {
  return <div ref={ref} className={cn('p-6 pt-0', className)} {...props} />;
}

function CardFooter({ className, ref, ...props }: React.ComponentProps<'div'>): JSX.Element {
  return <div ref={ref} className={cn('flex items-center p-6 pt-0', className)} {...props} />;
}

export { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle };
