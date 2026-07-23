import { Button } from '@shared/ui/button.tsx';
import { Label } from '@shared/ui/label.tsx';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@shared/ui/tooltip.tsx';
import { HelpCircle, Plus } from 'lucide-react';
import type React from 'react';
import type { JSX } from 'react';
import { type Control, useFieldArray } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import { getPropertyDefault } from '../../lib/schema-defaults.ts';
import { getUIHints, shouldRenderAsFields } from '../../lib/template.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';
import { useArrayFieldSensors } from './array-field-sensors.ts';
import { SortableDragList } from './array-field-sortable.tsx';
import { setArrayFieldComponent } from './ObjectFieldRenderer.tsx';
import { renderTupleFields } from './TupleFieldRenderer.tsx';

interface ArrayFieldProps {
  name: string;
  label: string;
  description?: string | undefined;
  schema: JSONSchemaProperty;
  register: FormRegisterFunction;
  control: Control<Record<string, unknown>>;
  errors: FormErrors;
}

function resolveItemSchema(schema: JSONSchemaProperty): JSONSchemaProperty {
  const raw = schema.items;
  return Array.isArray(raw) ? (raw[0] ?? { type: 'string' }) : (raw ?? { type: 'string' });
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
  name,
  label,
  description,
  schema,
  register,
  control,
  errors,
}: Readonly<ArrayFieldProps>): React.ReactElement {
  const { t } = useTranslation('omakase.editor');
  const { fields, append, remove, move } = useFieldArray({ control, name: name as never });
  const itemSchema = resolveItemSchema(schema);
  const defaultItem = getPropertyDefault(itemSchema as Record<string, unknown>);
  const uiHints = getUIHints(schema);
  const sensors = useArrayFieldSensors();

  if (shouldRenderAsFields(schema)) {
    return (
      renderTupleFields({
        name,
        label,
        description,
        schema,
        register,
        errors,
        uiHints,
        defaultFieldLabel: (index: number): string => t('fields.defaultFieldLabel', { index }),
      }) ?? <div />
    );
  }

  return (
    <div className="space-y-4">
      <ArrayFieldHeader
        label={label}
        description={description}
        addLabel={t('fields.addItem')}
        onAdd={() => append(defaultItem)}
      />
      {fields.length === 0 ? (
        <ArrayFieldEmptyState message={t('fields.noItemsYet')} />
      ) : (
        <SortableDragList
          fields={fields}
          name={name}
          itemSchema={itemSchema}
          register={register}
          control={control}
          errors={errors}
          onRemove={remove}
          sensors={sensors}
          onMove={move}
        />
      )}
    </div>
  );
}

// Register this component with ObjectFieldRenderer to break circular import
setArrayFieldComponent(ArrayField);

export { ArrayField };
