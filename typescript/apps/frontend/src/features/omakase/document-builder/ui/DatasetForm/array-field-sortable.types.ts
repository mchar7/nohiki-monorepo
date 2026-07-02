import type { Control } from 'react-hook-form';
import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';

interface SortableDragListProps {
  readonly fields: { id: string }[];
  readonly name: string;
  readonly itemSchema: JSONSchemaProperty;
  readonly register: FormRegisterFunction;
  readonly control: Control<Record<string, unknown>>;
  readonly errors: FormErrors;
  readonly onRemove: (index: number) => void;
  readonly sensors: ReturnType<typeof import('@dnd-kit/core').useSensors>;
  readonly onMove: (from: number, to: number) => void;
}

export type { SortableDragListProps };
