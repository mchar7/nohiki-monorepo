import { Button } from '@shared/ui/button.tsx';
import { Label } from '@shared/ui/label.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@shared/ui/tooltip.tsx';
import { HelpCircle, Plus } from 'lucide-react';
import type { JSX, ReactNode } from 'react';
import { useArrayFieldSensors } from './array-field-sensors.ts';
import { SortableDragList } from './array-field-sortable.tsx';

interface ArrayFieldProps {
  readonly label: string;
  readonly description: string | undefined;
  readonly addLabel: string;
  readonly emptyMessage: string;
  readonly fields: { id: string }[];
  readonly items: ReactNode[];
  readonly onAdd: () => void;
  readonly onRemove: (index: number) => void;
  readonly onMove: (from: number, to: number) => void;
}

function ArrayFieldEmptyState({ message }: { readonly message: string }): JSX.Element {
  return (
    <div className="rounded-lg border border-muted-foreground/25 border-dashed bg-muted/10 py-6 text-center">
      <p className="text-muted-foreground text-sm">{message}</p>
    </div>
  );
}

function ArrayFieldHeader({
  label,
  description,
  addLabel,
  onAdd,
}: {
  readonly label: string;
  readonly description: string | undefined;
  readonly addLabel: string;
  readonly onAdd: () => void;
}): JSX.Element {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Label className="font-medium text-sm">{label}</Label>
        {description ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild={true}>
                <HelpCircle className="size-4 cursor-help text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-xs">
                <p className="text-sm">{description}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : null}
      </div>
      <Button type="button" variant="outline" size="sm" onClick={onAdd} className="h-8">
        <Plus className="mr-2 size-4" />
        {addLabel}
      </Button>
    </div>
  );
}

function ArrayField({
  label,
  description,
  addLabel,
  emptyMessage,
  fields,
  items,
  onAdd,
  onRemove,
  onMove,
}: ArrayFieldProps): JSX.Element {
  const sensors = useArrayFieldSensors();

  return (
    <div className="space-y-4">
      <ArrayFieldHeader label={label} description={description} addLabel={addLabel} onAdd={onAdd} />
      {fields.length === 0 ? (
        <ArrayFieldEmptyState message={emptyMessage} />
      ) : (
        <SortableDragList
          fields={fields}
          items={items}
          onRemove={onRemove}
          sensors={sensors}
          onMove={onMove}
        />
      )}
    </div>
  );
}

export { ArrayField };
