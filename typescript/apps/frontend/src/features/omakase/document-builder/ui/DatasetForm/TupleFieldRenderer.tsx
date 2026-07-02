import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import type { UIHints } from '../../lib/template.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';
import { FieldLabelWithTooltip } from './FieldLabelWithTooltip.tsx';
import { FormField } from './FormField.tsx';

/** Maximum number of grid columns for inline field rendering */
const MAX_GRID_COLUMNS: number = 3;
/** Maximum number of items to render as inline fields instead of a list */
const INLINE_FIELDS_MAX_ITEMS: number = 3;

function getFormFieldType(itemSchema: JSONSchemaProperty): 'date' | 'number' | 'string' {
  if (itemSchema.format === 'date') {
    return 'date';
  }
  if (itemSchema.type === 'number') {
    return 'number';
  }
  return 'string';
}

function getFieldPlaceholder(placeholder: unknown, example: unknown): string {
  if (typeof placeholder === 'string') {
    return placeholder;
  }
  if (typeof example === 'string') {
    return example;
  }
  return '';
}

function getGridClassName(direction: string | undefined, maxItems: number): string {
  const colsClass: string =
    direction === 'column' ? 'grid-cols-1' : `grid-cols-${Math.min(maxItems, MAX_GRID_COLUMNS)}`;
  return `grid gap-2 ${colsClass}`;
}

interface TupleFieldsParams {
  name: string;
  label: string;
  description: string | undefined;
  schema: JSONSchemaProperty;
  register: FormRegisterFunction;
  errors: FormErrors;
  uiHints: UIHints;
  defaultFieldLabel: (index: number) => string;
}

export function renderTupleFields({
  name,
  label,
  description,
  schema,
  register,
  errors,
  uiHints,
  defaultFieldLabel,
}: TupleFieldsParams): React.ReactElement | null {
  // Handle tuple arrays (like date ranges) as individual fields
  if (schema.prefixItems) {
    return (
      <div className="space-y-3">
        <FieldLabelWithTooltip label={label} description={description} />
        <div className={getGridClassName(uiHints.direction, 2)}>
          {schema.prefixItems?.map((itemSchema: JSONSchemaProperty, index: number) => {
            const fieldName = `${name}.${index}`;
            const fieldLabel =
              uiHints.fieldNames?.[index] || itemSchema.title || defaultFieldLabel(index + 1);

            return (
              <FormField
                key={fieldName}
                name={fieldName}
                label={fieldLabel}
                type={getFormFieldType(itemSchema)}
                register={register}
                errors={errors}
                placeholder={getFieldPlaceholder(uiHints.placeholder, itemSchema.examples?.[0])}
              />
            );
          })}
        </div>
      </div>
    );
  }

  // Handle fixed-size arrays as individual fields
  if (schema.maxItems && schema.maxItems <= INLINE_FIELDS_MAX_ITEMS) {
    const { maxItems } = schema;
    // items can be JSONSchemaProperty | JSONSchemaProperty[] (tuple schema); normalise to single
    const itemSchema = Array.isArray(schema.items) ? schema.items[0] : schema.items;
    return (
      <div className="space-y-3">
        <FieldLabelWithTooltip label={label} description={description} />
        <div className={getGridClassName(uiHints.direction, maxItems)}>
          {Array.from({ length: maxItems }, (_, index) => {
            const fieldName = `${name}.${index}`;
            const fieldLabel = uiHints.fieldNames?.[index] || defaultFieldLabel(index + 1);
            const fieldType: 'number' | 'string' =
              itemSchema?.type === 'number' ? 'number' : 'string';

            return (
              <FormField
                key={fieldName}
                name={fieldName}
                label={fieldLabel}
                type={fieldType}
                register={register}
                errors={errors}
                placeholder={getFieldPlaceholder(uiHints.placeholder, itemSchema?.examples?.[0])}
              />
            );
          })}
        </div>
      </div>
    );
  }

  return <div />;
}
