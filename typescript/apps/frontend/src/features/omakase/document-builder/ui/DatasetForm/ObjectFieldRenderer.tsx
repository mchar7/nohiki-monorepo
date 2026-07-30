import { Input } from '@shared/ui/input.tsx';
import { Textarea } from '@shared/ui/textarea.tsx';
import type { JSX } from 'react';
import { type Control, useFieldArray } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import { getPropertyDefault } from '../../lib/schema-defaults.ts';
import { getUIHints, shouldRenderAsFields } from '../../lib/template.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';
import { ArrayField } from './ArrayField.tsx';
import { FormField } from './FormField.tsx';
import { getFieldTitle, getFieldWidget, getInputType, renderFieldLabel } from './shared.tsx';
import { renderTupleFields } from './TupleFieldRenderer.tsx';

interface BaseFieldParams {
  key: string;
  fieldName: string;
  fieldTitle: string;
  fieldDescription: string | undefined;
  fieldSchema: JSONSchemaProperty;
  register: FormRegisterFunction;
  errors: FormErrors;
}

interface ObjectFieldParams extends BaseFieldParams {
  control: Control<Record<string, unknown>>;
}

function renderObjectField({
  key,
  fieldName,
  fieldTitle,
  fieldDescription,
  fieldSchema,
  register,
  control,
  errors,
}: ObjectFieldParams): React.ReactNode {
  return (
    <div key={key} className="space-y-3">
      {renderFieldLabel(fieldTitle, fieldDescription)}
      <div className="space-y-3 rounded-lg border bg-muted/20 px-3 py-3 sm:px-5">
        {renderObjectFields({
          baseName: fieldName,
          schema: fieldSchema,
          register,
          control,
          errors,
        })}
      </div>
    </div>
  );
}

interface ObjectFieldsParams {
  baseName: string;
  schema: JSONSchemaProperty;
  register: FormRegisterFunction;
  control: Control<Record<string, unknown>>;
  errors: FormErrors;
}

interface ArraySchemaFieldProps {
  name: string;
  label: string;
  description: string | undefined;
  required?: boolean | undefined;
  schema: JSONSchemaProperty;
  register: FormRegisterFunction;
  control: Control<Record<string, unknown>>;
  errors: FormErrors;
}

interface ArrayItemSchemaFieldProps {
  itemSchema: JSONSchemaProperty;
  name: string;
  index: number;
  itemLabel: string;
  placeholderFallback: string;
  register: FormRegisterFunction;
  control: Control<Record<string, unknown>>;
  errors: FormErrors;
}

function getItemPlaceholder(itemSchema: JSONSchemaProperty, fallback: string): string {
  const placeholder = itemSchema['x-placeholder'];
  if (typeof placeholder === 'string') {
    return placeholder;
  }
  const example = itemSchema.examples?.[0];
  return typeof example === 'string' ? example : fallback;
}

function ArrayItemSchemaField({
  itemSchema,
  name,
  index,
  itemLabel,
  placeholderFallback,
  register,
  control,
  errors,
}: Readonly<ArrayItemSchemaFieldProps>): JSX.Element {
  const fieldName = `${name}.${index}`;

  if (itemSchema.type === 'object') {
    return (
      <div className="space-y-3">
        {renderObjectFields({
          baseName: fieldName,
          schema: itemSchema,
          register,
          control,
          errors,
        })}
      </div>
    );
  }

  if (itemSchema.type === 'array') {
    return (
      <ArraySchemaField
        name={fieldName}
        label={itemSchema.title || itemLabel}
        description={itemSchema.description}
        schema={itemSchema}
        register={register}
        control={control}
        errors={errors}
      />
    );
  }

  if (itemSchema['x-widget'] === 'textarea') {
    return (
      <Textarea
        {...register(fieldName)}
        placeholder={getItemPlaceholder(itemSchema, placeholderFallback)}
        className="min-h-20 w-full resize-y"
        rows={3}
      />
    );
  }

  return (
    <Input
      {...register(fieldName)}
      type={itemSchema.type === 'number' || itemSchema.type === 'integer' ? 'number' : 'text'}
      placeholder={getItemPlaceholder(itemSchema, placeholderFallback)}
      className="w-full"
    />
  );
}

function ArraySchemaField({
  name,
  label,
  description,
  required,
  schema,
  register,
  control,
  errors,
}: Readonly<ArraySchemaFieldProps>): JSX.Element {
  const { t } = useTranslation('omakase.editor');
  const { fields, append, remove, move } = useFieldArray({ control, name: name as never });
  const rawItemSchema = schema.items;
  const itemSchema = Array.isArray(rawItemSchema)
    ? (rawItemSchema[0] ?? { type: 'string' })
    : (rawItemSchema ?? { type: 'string' });
  const defaultItem = getPropertyDefault(itemSchema as Record<string, unknown>);
  const uiHints = getUIHints(schema);

  if (shouldRenderAsFields(schema)) {
    return (
      renderTupleFields({
        name,
        label,
        description,
        schema,
        required,
        register,
        errors,
        uiHints,
        defaultFieldLabel: (index: number): string => t('fields.defaultFieldLabel', { index }),
      }) ?? <div />
    );
  }

  const items = fields.map((field, index) => (
    <ArrayItemSchemaField
      key={field.id}
      itemSchema={itemSchema}
      name={name}
      index={index}
      itemLabel={t('fields.defaultFieldLabel', { index: index + 1 })}
      placeholderFallback={t('fields.itemPlaceholder')}
      register={register}
      control={control}
      errors={errors}
    />
  ));

  return (
    <ArrayField
      label={label}
      description={description}
      addLabel={t('fields.addItem')}
      emptyMessage={t('fields.noItemsYet')}
      fields={fields}
      items={items}
      onAdd={() => append(defaultItem)}
      onRemove={remove}
      onMove={move}
    />
  );
}

function renderObjectFields({
  baseName,
  schema,
  register,
  control,
  errors,
}: ObjectFieldsParams): React.ReactNode {
  if (!schema?.properties) {
    return null;
  }

  return Object.entries(schema.properties).map(([key, fieldSchema]: [string, JSONSchemaProperty]) =>
    renderSingleObjectField({ key, baseName, fieldSchema, schema, register, control, errors }),
  );
}

interface SingleObjectFieldParams {
  key: string;
  baseName: string;
  fieldSchema: JSONSchemaProperty;
  schema: JSONSchemaProperty;
  register: FormRegisterFunction;
  control: Control<Record<string, unknown>>;
  errors: FormErrors;
}

interface ArrayFieldParams extends ObjectFieldParams {
  isRequired: boolean | undefined;
}

function renderArrayField({
  key,
  fieldName,
  fieldTitle,
  fieldDescription,
  fieldSchema,
  isRequired,
  register,
  control,
  errors,
}: ArrayFieldParams): React.ReactNode {
  return (
    <ArraySchemaField
      key={key}
      name={fieldName}
      label={fieldTitle}
      description={fieldDescription}
      required={isRequired}
      schema={fieldSchema}
      register={register}
      control={control}
      errors={errors}
    />
  );
}

interface PrimitiveFieldParams extends BaseFieldParams {
  isRequired: boolean | undefined;
}

function renderPrimitiveField({
  key,
  fieldName,
  fieldTitle,
  fieldDescription,
  fieldSchema,
  isRequired,
  register,
  errors,
}: PrimitiveFieldParams): React.ReactNode {
  const inputType = getInputType(fieldSchema);
  const widget = getFieldWidget(fieldSchema, key);

  return (
    <FormField
      key={key}
      name={fieldName}
      label={fieldTitle}
      type={inputType as 'string' | 'number' | 'integer' | 'boolean' | 'date' | 'text'}
      required={isRequired}
      description={fieldDescription}
      register={register}
      errors={errors}
      placeholder={String(
        fieldSchema['x-placeholder'] || fieldSchema.examples?.[0] || fieldSchema.default || '',
      )}
      widget={widget}
    />
  );
}

function buildFieldContext(
  key: string,
  baseName: string,
  fieldSchema: JSONSchemaProperty,
): {
  fieldName: string;
  fieldTitle: string;
  fieldDescription: string | undefined;
} {
  return {
    fieldName: baseName ? `${baseName}.${key}` : key,
    fieldTitle: getFieldTitle(fieldSchema, key),
    fieldDescription: fieldSchema.description,
  };
}

function renderSingleObjectField({
  key,
  baseName,
  fieldSchema,
  schema,
  register,
  control,
  errors,
}: SingleObjectFieldParams): React.ReactNode {
  const { fieldName, fieldTitle, fieldDescription } = buildFieldContext(key, baseName, fieldSchema);
  const isRequired = schema.required?.includes(key);

  if (fieldSchema.type === 'object') {
    return renderObjectField({
      key,
      fieldName,
      fieldTitle,
      fieldDescription,
      fieldSchema,
      register,
      control,
      errors,
    });
  }

  if (fieldSchema.type === 'array') {
    return renderArrayField({
      key,
      fieldName,
      fieldTitle,
      fieldDescription,
      fieldSchema,
      isRequired,
      register,
      control,
      errors,
    });
  }

  return renderPrimitiveField({
    key,
    fieldName,
    fieldTitle,
    fieldDescription,
    fieldSchema,
    isRequired,
    register,
    errors,
  });
}

export { renderObjectFields };
