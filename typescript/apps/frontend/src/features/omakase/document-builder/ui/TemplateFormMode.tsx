import { Input } from '@shared/ui/input.tsx';
import { Label } from '@shared/ui/label.tsx';
import { Textarea } from '@shared/ui/textarea.tsx';
import { FileText } from 'lucide-react';
import type { JSX } from 'react';
import { useTranslation } from 'react-i18next';
import type { ContentSchema, FieldDescriptor } from '../lib/TemplateFormModeModel.ts';
import { flattenSchema } from '../lib/TemplateFormModeModel.ts';

/**
 * Template form payload. Structurally a JSON record; declared here at the
 * feature boundary so callers can pass their own typed aliases without
 * forcing a cross-slice import.
 */
type TemplateFormData = Record<string, unknown>;

interface TemplateFormModeProps {
  readonly contentSchema: ContentSchema;
  readonly data: TemplateFormData;
  readonly onDataChange: (data: TemplateFormData) => void;
}

function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
  const parts = path.split('.');
  let current: unknown = obj;
  for (const part of parts) {
    if (current === null || current === undefined || typeof current !== 'object') {
      return;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

function setNestedValue(
  obj: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const clone = structuredClone(obj);
  const parts = path.split('.');
  let current: Record<string, unknown> = clone;
  for (let i = 0; i < parts.length - 1; i += 1) {
    const part = parts[i] as string;
    if (!(part in current) || typeof current[part] !== 'object' || current[part] === null) {
      current[part] = {};
    }
    current = current[part] as Record<string, unknown>;
  }
  const lastPart = parts.at(-1) as string;
  current[lastPart] = value;
  return clone;
}

function SchemaFormField({
  field,
  value,
  onChange,
}: {
  readonly field: FieldDescriptor;
  readonly value: string;
  readonly onChange: (path: string, value: string) => void;
}): JSX.Element {
  const fieldId = `template-form-${field.path}`;
  const descriptionId = `${fieldId}-desc`;

  const ariaProps = {
    id: fieldId,
    'aria-label': field.label,
    ...(field.description ? { 'aria-describedby': descriptionId } : {}),
  };

  return (
    <div className="space-y-2">
      <Label htmlFor={fieldId} className="font-medium text-sm">
        {field.label}
      </Label>
      {field.description ? (
        <p id={descriptionId} className="text-muted-foreground text-xs">
          {field.description}
        </p>
      ) : null}
      {field.fieldType === 'textarea' ? (
        <Textarea
          {...ariaProps}
          value={value}
          onChange={(e: React.ChangeEvent<HTMLTextAreaElement>): void =>
            onChange(field.path, e.target.value)
          }
          rows={3}
        />
      ) : (
        <Input
          {...ariaProps}
          type={field.fieldType === 'number' ? 'number' : 'text'}
          value={value}
          onChange={(e: React.ChangeEvent<HTMLInputElement>): void =>
            onChange(field.path, e.target.value)
          }
        />
      )}
    </div>
  );
}

function TemplateFormMode({
  contentSchema,
  data,
  onDataChange,
}: TemplateFormModeProps): JSX.Element {
  const { t } = useTranslation('omakase.templateStudio');
  const fields = flattenSchema(contentSchema, '');

  const handleFieldChange = (path: string, value: string): void => {
    const updated = setNestedValue(data as Record<string, unknown>, path, value);
    onDataChange(updated);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b bg-muted/20 px-4">
        <FileText className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="font-medium text-sm">{t('panels.formFields')}</span>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-2xl space-y-4">
          {fields.map((field) => (
            <SchemaFormField
              key={field.path}
              field={field}
              value={String(getNestedValue(data as Record<string, unknown>, field.path) ?? '')}
              onChange={handleFieldChange}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export { TemplateFormMode };
