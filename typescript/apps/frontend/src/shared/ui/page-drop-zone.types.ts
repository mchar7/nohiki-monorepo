import type { ReactNode } from 'react';

interface PageDropZoneProps {
  readonly children: ReactNode;
  readonly onDrop: (files: FileList) => void;
  readonly className?: string;
  readonly disabled?: boolean;
}

export type { PageDropZoneProps };
