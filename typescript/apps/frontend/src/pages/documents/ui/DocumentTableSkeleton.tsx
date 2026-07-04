import type { JSX } from 'react';
import { Card, CardContent } from '@/shared/ui/card.tsx';
import { Skeleton } from '@/shared/ui/skeleton.tsx';

const DOC_SKELETON_KEYS = ['dsk-1', 'dsk-2', 'dsk-3', 'dsk-4', 'dsk-5'] as const;

/** Skeleton matching the UnifiedDocumentCard layout: stacked cards with icon + text + badge + action */
function DocumentTableSkeleton(): JSX.Element {
  return (
    <div className="space-y-3">
      {DOC_SKELETON_KEYS.map((key) => (
        <Card key={key}>
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              {/* File icon */}
              <Skeleton className="size-8 shrink-0 rounded" />
              {/* Text content */}
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-5 w-16 rounded-md" />
                </div>
                <Skeleton className="h-3.5 w-20" />
              </div>
              {/* Action button */}
              <Skeleton className="h-8 w-8 shrink-0 rounded-md" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export { DocumentTableSkeleton };
