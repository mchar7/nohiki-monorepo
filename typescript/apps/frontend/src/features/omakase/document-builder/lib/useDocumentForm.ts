import { logger, sanitizeData, useFormAutoSave } from '@shared/lib/index.ts';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import type { TemplateResponse } from '@/shared/api';
import type { JSONSchemaProperty } from '@/shared/model/index.ts';
import type { DatasetData } from '../model/index.ts';
import { useDocumentBuilderStore } from '../model/index.ts';

function resolveSchema(schema: JSONSchemaProperty): JSONSchemaProperty | null {
  try {
    if (!schema || typeof schema !== 'object') {
      return null;
    }

    if (schema.type || schema.properties) {
      return schema;
    }

    if ('schema' in schema && schema.schema) {
      return schema.schema as JSONSchemaProperty;
    }

    return null;
  } catch (error) {
    logger.error('DocumentForm: Failed to resolve schema', error);
    return null;
  }
}

interface SchemaState {
  schemaData: JSONSchemaProperty | null;
  isLoadingSchema: boolean;
  schemaError: string | null;
}

/** Derives schema state from the current template's content_schema. */
function deriveSchemaState(
  contentSchema: TemplateResponse['content_schema'] | undefined,
  t: (key: string) => string,
): SchemaState {
  if (!contentSchema) {
    return { schemaData: null, isLoadingSchema: false, schemaError: null };
  }

  try {
    return {
      schemaData: contentSchema as JSONSchemaProperty,
      isLoadingSchema: false,
      schemaError: null,
    };
  } catch (error) {
    logger.error('DocumentForm schema error', error);
    return {
      schemaData: null,
      isLoadingSchema: false,
      schemaError: error instanceof Error ? error.message : t('errors.schemaFetchFailed'),
    };
  }
}

interface UseDocumentFormProps {
  datasetId: string;
  onDataChange?: ((isDirty: boolean) => void) | undefined;
}

type TypedForm = ReturnType<typeof useForm<Record<string, unknown>>>;

interface DocumentFormResult {
  dataset: import('../model/index.ts').Dataset | undefined;
  template: TemplateResponse | null;
  resolvedSchema: JSONSchemaProperty | null;
  isValid: boolean;
  validationErrors: string[];
  isLoadingSchema: boolean;
  form: {
    register: TypedForm['register'];
    handleSubmit: TypedForm['handleSubmit'];
    control: TypedForm['control'];
    errors: TypedForm['formState']['errors'];
    onSubmit: (data: Record<string, unknown>) => void;
  };
}

function useSchemaDerivation(contentSchema: TemplateResponse['content_schema'] | undefined): {
  resolvedSchema: JSONSchemaProperty | null;
  isValid: boolean;
  validationErrors: string[];
  isLoadingSchema: boolean;
} {
  const { t } = useTranslation('omakase.editor');
  const [schemaState, setSchemaState] = useState<SchemaState>({
    schemaData: null,
    isLoadingSchema: false,
    schemaError: null,
  });

  useEffect(() => {
    setSchemaState(deriveSchemaState(contentSchema, t));
  }, [contentSchema, t]);

  const resolvedSchema = schemaState.schemaData ? resolveSchema(schemaState.schemaData) : null;
  return {
    resolvedSchema,
    isValid: !(schemaState.schemaError || schemaState.isLoadingSchema) && Boolean(resolvedSchema),
    validationErrors: schemaState.schemaError ? [schemaState.schemaError] : [],
    isLoadingSchema: schemaState.isLoadingSchema,
  };
}

export function useDocumentForm({
  datasetId,
  onDataChange,
}: UseDocumentFormProps): DocumentFormResult {
  const datasets = useDocumentBuilderStore((state) => state.datasets);
  const currentTemplate = useDocumentBuilderStore((state) => state.currentTemplate);
  const updateDataset = useDocumentBuilderStore((state) => state.updateDataset);

  const dataset = (() => {
    const index = new Map(datasets.map((d) => [d.id, d]));
    return index.get(datasetId);
  })();

  const schema = useSchemaDerivation(currentTemplate?.content_schema);

  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isDirty },
    reset,
    watch,
  } = useForm<Record<string, unknown>>({ defaultValues: dataset?.data ?? {} });

  useFormAutoSave({
    data: watch(),
    isDirty,
    onSave: (data: Record<string, unknown>): void => {
      if (!dataset) {
        return;
      }
      // DatasetData is a structural alias for Record<string, unknown>, so the form's
      // generic argument value satisfies it directly with no cast.
      updateDataset(dataset.id, { data });
      reset(data, { keepValues: true });
    },
    enabled: Boolean(dataset),
  });

  useEffect(() => {
    onDataChange?.(isDirty);
  }, [isDirty, onDataChange]);

  return {
    dataset,
    template: currentTemplate,
    ...schema,
    form: {
      register,
      handleSubmit,
      control,
      errors,
      onSubmit: (data: Record<string, unknown>): void => {
        if (!dataset) {
          return;
        }
        updateDataset(dataset.id, { data: sanitizeData(data, true) as DatasetData });
      },
    },
  };
}
