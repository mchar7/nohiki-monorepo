import { Input, Textarea } from '@shared/ui/index.ts';
import type { JSX } from 'react';
import type { Control } from 'react-hook-form';
import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import type { FormErrors, FormRegisterFunction } from '../../model/index.ts';
import { renderObjectFields } from './ObjectFieldRenderer.tsx';

function getItemPlaceholder(itemSchema: JSONSchemaProperty | undefined, fallback: string): string {
  const placeholder = itemSchema?.['x-placeholder'];
  if (typeof placeholder === 'string') {
    return placeholder;
  }
  const example = itemSchema?.examples?.[0];
  if (typeof example === 'string') {
    return example;
  }
  return fallback;
}

function getInputType(itemSchema: JSONSchemaProperty | undefined): 'number' | 'text' {
  return itemSchema?.type === 'number' || itemSchema?.type === 'integer' ? 'number' : 'text';
}

interface ArrayItemFieldParams {
  itemSchema: JSONSchemaProperty | undefined;
  name: string;
  index: number;
  placeholderFallback: string;
  register: FormRegisterFunction;
  control: Control<Record<string, unknown>>;
  errors: FormErrors;
}

function renderArrayItemField({
  itemSchema,
  name,
  index,
  placeholderFallback,
  register,
  control,
  errors,
}: ArrayItemFieldParams): JSX.Element {
  if (itemSchema?.type === 'object') {
    return (
      <div className="space-y-3">
        {renderObjectFields({
          baseName: `${name}.${index}`,
          schema: itemSchema,
          register,
          control,
          errors,
        })}
      </div>
    );
  }
  if (itemSchema?.['x-widget'] === 'textarea') {
    return (
      <Textarea
        {...register(`${name}.${index}`)}
        placeholder={getItemPlaceholder(itemSchema, placeholderFallback)}
        className="min-h-20 w-full resize-y"
        rows={3}
      />
    );
  }
  return (
    <Input
      {...register(`${name}.${index}`)}
      type={getInputType(itemSchema)}
      placeholder={getItemPlaceholder(itemSchema, placeholderFallback)}
      className="w-full"
    />
  );
}

export { renderArrayItemField };
