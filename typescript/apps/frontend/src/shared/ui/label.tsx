import { Root } from '@radix-ui/react-label';
import { cva, type VariantProps } from 'class-variance-authority';

import type { JSX } from 'react';
import { cn } from '@/shared/lib/utils/utils.ts';

const labelVariants = cva(
  'text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
);

function Label({
  className,
  ref,
  ...props
}: React.ComponentProps<typeof Root> & VariantProps<typeof labelVariants>): JSX.Element {
  return <Root ref={ref} className={cn(labelVariants(), className)} {...props} />;
}

export { Label };
