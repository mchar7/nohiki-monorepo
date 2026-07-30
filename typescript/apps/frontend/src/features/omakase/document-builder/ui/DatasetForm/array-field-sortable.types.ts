import type { SensorDescriptor, SensorOptions } from '@dnd-kit/core';
import type { ReactNode } from 'react';

interface SortableDragListProps {
  readonly fields: { id: string }[];
  readonly items: ReactNode[];
  readonly onRemove: (index: number) => void;
  readonly sensors: SensorDescriptor<SensorOptions>[];
  readonly onMove: (from: number, to: number) => void;
}

export type { SortableDragListProps };
