import type { JSX } from 'react';
import { useRef } from 'react';
import { cn, useSwipeToDismiss } from '@/shared/lib/index.ts';
import type { BottomSheetProps } from './bottom-sheet.types.ts';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from './sheet.tsx';

/** Mobile-optimized bottom sheet using Shadcn Sheet with side="bottom". */
function BottomSheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
}: BottomSheetProps): JSX.Element {
  const contentRef = useRef<HTMLDivElement>(null);
  useSwipeToDismiss({
    ref: contentRef,
    onDismiss: () => onOpenChange(false),
    direction: 'down',
    enabled: open,
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        ref={contentRef}
        side="bottom"
        className={cn('max-h-[85vh] rounded-t-xl', className)}
        {...(description ? {} : { 'aria-describedby': undefined })}
      >
        <div className="mx-auto mb-4 h-1.5 w-12 rounded-full bg-muted" />
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {description ? <SheetDescription>{description}</SheetDescription> : null}
        </SheetHeader>
        <div className="overflow-y-auto">{children}</div>
      </SheetContent>
    </Sheet>
  );
}

export { BottomSheet };
