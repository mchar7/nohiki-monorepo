import {
  CollapsibleContent as RadixCollapsibleContent,
  CollapsibleTrigger as RadixCollapsibleTrigger,
  Root,
} from '@radix-ui/react-collapsible';
import type { JSX } from 'react';

function Collapsible({ ...props }: React.ComponentProps<typeof Root>): JSX.Element {
  return <Root data-slot="collapsible" {...props} />;
}

function CollapsibleTrigger({
  ...props
}: React.ComponentProps<typeof RadixCollapsibleTrigger>): JSX.Element {
  return <RadixCollapsibleTrigger data-slot="collapsible-trigger" {...props} />;
}

function CollapsibleContent({
  ...props
}: React.ComponentProps<typeof RadixCollapsibleContent>): JSX.Element {
  return <RadixCollapsibleContent data-slot="collapsible-content" {...props} />;
}

export { Collapsible, CollapsibleContent, CollapsibleTrigger };
