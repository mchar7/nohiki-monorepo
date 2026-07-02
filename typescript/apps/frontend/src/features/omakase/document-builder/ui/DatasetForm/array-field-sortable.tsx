import { closestCenter, DndContext, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Button, Card } from '@shared/ui/index.ts';
import { GripVertical, Trash2 } from 'lucide-react';
import type { JSX } from 'react';
import type { Control } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';
import { renderArrayItemField } from './array-field-item.tsx';
import type { SortableDragListProps } from './array-field-sortable.types.ts';

/** Opacity applied to an item while being dragged */
const DRAGGING_OPACITY: number = 0.5;
/** Default opacity for non-dragging items */
const DEFAULT_OPACITY: number = 1;

interface SortableItemProps {
  id: string;
  index: number;
  name: string;
  itemSchema: JSONSchemaProperty;
  register: FormRegisterFunction;
  control: Control<Record<string, unknown>>;
  errors: FormErrors;
  onRemove: (index: number) => void;
}

function SortableItem({
  id,
  index,
  name,
  itemSchema,
  register,
  control,
  errors,
  onRemove,
}: Readonly<SortableItemProps>): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? DRAGGING_OPACITY : DEFAULT_OPACITY,
  };

  return (
    <Card ref={setNodeRef} style={style} className="px-2 py-3">
      <div className="flex gap-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="size-6 shrink-0 cursor-grab p-0 text-muted-foreground hover:text-foreground active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="size-3" />
        </Button>
        <div className="flex-1">
          {renderArrayItemField({
            itemSchema,
            name,
            index,
            placeholderFallback: t('fields.itemPlaceholder'),
            register,
            control,
            errors,
          })}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onRemove(index)}
          className="size-6 shrink-0 p-0 text-muted-foreground hover:text-destructive"
        >
          <Trash2 className="size-3" />
        </Button>
      </div>
    </Card>
  );
}

/** Renders the DnD-sortable list of array items inside a DndContext. */
function SortableDragList({
  fields,
  name,
  itemSchema,
  register,
  control,
  errors,
  onRemove,
  sensors,
  onMove,
}: Readonly<SortableDragListProps>): JSX.Element {
  const handleDragEnd = (event: DragEndEvent): void => {
    const { active, over } = event;
    if (active.id !== over?.id) {
      onMove(
        fields.findIndex((f) => f.id === active.id),
        fields.findIndex((f) => f.id === over?.id),
      );
    }
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={fields.map((f) => f.id)} strategy={verticalListSortingStrategy}>
        <div className="space-y-3">
          {fields.map((field, index) => (
            <SortableItem
              key={field.id}
              id={field.id}
              index={index}
              name={name}
              itemSchema={itemSchema}
              register={register}
              control={control}
              errors={errors}
              onRemove={onRemove}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}

export { SortableDragList };
