import type { JSX } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';

function Table({ className, ref, ...props }: React.ComponentProps<'table'>): JSX.Element {
  return (
    <div className="relative w-full overflow-auto">
      <table ref={ref} className={cn('w-full caption-bottom text-sm', className)} {...props} />
    </div>
  );
}

function TableHeader({ className, ref, ...props }: React.ComponentProps<'thead'>): JSX.Element {
  return <thead ref={ref} className={cn('[&_tr]:border-b', className)} {...props} />;
}

function TableBody({ className, ref, ...props }: React.ComponentProps<'tbody'>): JSX.Element {
  return (
    <tbody
      ref={ref}
      className={cn('[&_tr:last-child]:border-0 [&_tr:nth-child(even)]:bg-muted/30', className)}
      {...props}
    />
  );
}

export function TableFooter({
  className,
  ref,
  ...props
}: React.ComponentProps<'tfoot'>): JSX.Element {
  return (
    <tfoot
      ref={ref}
      className={cn('border-t bg-muted/50 font-medium [&>tr]:last:border-b-0', className)}
      {...props}
    />
  );
}

function TableRow({ className, ref, ...props }: React.ComponentProps<'tr'>): JSX.Element {
  return (
    <tr
      ref={ref}
      className={cn(
        'border-b transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset data-[state=selected]:bg-muted',
        className,
      )}
      {...props}
    />
  );
}

function TableHead({
  className,
  ref,
  scope = 'col',
  ...props
}: React.ComponentProps<'th'>): JSX.Element {
  return (
    <th
      ref={ref}
      scope={scope}
      className={cn(
        'h-10 px-2 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0 *:[[role=checkbox]]:translate-y-0.5',
        className,
      )}
      {...props}
    />
  );
}

function TableCell({ className, ref, ...props }: React.ComponentProps<'td'>): JSX.Element {
  return (
    <td
      ref={ref}
      className={cn(
        'p-2 align-middle [&:has([role=checkbox])]:pr-0 *:[[role=checkbox]]:translate-y-0.5',
        className,
      )}
      {...props}
    />
  );
}

export function TableCaption({
  className,
  ref,
  ...props
}: React.ComponentProps<'caption'>): JSX.Element {
  return (
    <caption ref={ref} className={cn('mt-4 text-muted-foreground text-sm', className)} {...props} />
  );
}

export { Table, TableBody, TableCell, TableHead, TableHeader, TableRow };
