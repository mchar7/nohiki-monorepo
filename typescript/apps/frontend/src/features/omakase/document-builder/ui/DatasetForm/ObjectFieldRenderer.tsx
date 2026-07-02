import type { Control } from 'react-hook-form';
import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';
import { FormField } from './FormField.tsx';
import { getFieldTitle, getFieldWidget, getInputType, renderFieldLabel } from './shared.tsx';

// Forward declaration to avoid circular import
type ArrayFieldComponent = (props: {
  name: string;
  label: string;
  description?: string | undefined;
  schema: JSONSchemaProperty;
  register: FormRegisterFunction;
  control: Control<Record<string, unknown>>;
  errors: FormErrors;
}) => React.ReactElement;

// This will be set by ArrayField to avoid circular import
let ArrayFieldComponent: ArrayFieldComponent | null = null;

function setArrayFieldComponent(component: ArrayFieldComponent): void {
  ArrayFieldComponent = component;
}

interface BaseFieldParams {
  key: string;
  fieldName: string;
  fieldTitle: string;
  fieldDescription: string | undefined;
  fieldSchema: JSONSchemaProperty;
  register: FormRegisterFunction;
  errors: FormErrors;
}

interface DateRangeFieldParams extends BaseFieldParams {
  isRequired: boolean;
}

function renderDateRangeField({
  key,
  fieldName,
  fieldTitle,
  fieldDescription,
  fieldSchema,
  isRequired,
  register,
  errors,
}: DateRangeFieldParams): React.ReactNode {
  if (fieldSchema.prefixItems?.length !== 2) {
    return null;
  }

  const [startSchema, endSchema] = fieldSchema.prefixItems;
  if (!(startSchema && endSchema)) {
    return null;
  }

  return (
    <div key={key} className="space-y-3">
      {renderFieldLabel(fieldTitle, fieldDescription)}
      <div className="grid grid-cols-2 gap-2">
        <FormField
          name={`${fieldName}.0`}
          label={startSchema.title || 'Start'}
          type={startSchema.format === 'date' ? 'date' : 'string'}
          required={isRequired}
          description={startSchema.description}
          register={register}
          errors={errors}
          placeholder={String(startSchema.examples?.[0] || 'Start date')}
        />
        <FormField
          name={`${fieldName}.1`}
          label={endSchema.title || 'End'}
          type={endSchema.format === 'date' ? 'date' : 'string'}
          required={isRequired}
          description={endSchema.description}
          register={register}
          errors={errors}
          placeholder={String(endSchema.examples?.[0] || 'End date')}
        />
      </div>
    </div>
  );
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

function renderArrayField({
  key,
  fieldName,
  fieldTitle,
  fieldDescription,
  fieldSchema,
  register,
  control,
  errors,
}: ObjectFieldParams): React.ReactNode {
  if (!ArrayFieldComponent) {
    return null;
  }

  return (
    <ArrayFieldComponent
      key={key}
      name={fieldName}
      label={fieldTitle}
      description={fieldDescription}
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

  if (
    fieldSchema.type === 'array' &&
    fieldSchema.prefixItems &&
    fieldSchema.prefixItems.length === 2
  ) {
    return renderDateRangeField({
      key,
      fieldName,
      fieldTitle,
      fieldDescription,
      fieldSchema,
      isRequired: isRequired ?? false,
      register,
      errors,
    });
  }

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

export { renderObjectFields, setArrayFieldComponent };
