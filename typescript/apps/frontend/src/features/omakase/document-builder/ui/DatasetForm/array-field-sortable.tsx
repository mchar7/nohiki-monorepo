import { closestCenter, DndContext, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Button } from '@shared/ui/button.tsx';
import { Card } from '@shared/ui/card.tsx';
import { GripVertical, Trash2 } from 'lucide-react';
import type { JSX, ReactNode } from 'react';
import { ArrayFieldItem } from './array-field-item.tsx';
import type { SortableDragListProps } from './array-field-sortable.types.ts';

/** Opacity applied to an item while being dragged */
const DRAGGING_OPACITY: number = 0.5;
/** Default opacity for non-dragging items */
const DEFAULT_OPACITY: number = 1;

interface SortableItemProps {
  id: string;
  index: number;
  children: ReactNode;
  onRemove: (index: number) => void;
}

function SortableItem({ id, index, children, onRemove }: Readonly<SortableItemProps>): JSX.Element {
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
        <ArrayFieldItem>{children}</ArrayFieldItem>
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
  items,
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
            <SortableItem key={field.id} id={field.id} index={index} onRemove={onRemove}>
              {items[index]}
            </SortableItem>
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}

export { SortableDragList };
