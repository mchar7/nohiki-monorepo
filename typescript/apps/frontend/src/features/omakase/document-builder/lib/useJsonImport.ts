import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { DatasetData } from '../model/index.ts';

interface ImportResult {
  success: boolean;
  data?: DatasetData;
  errors?: string[];
}

interface ValidateJsonOptions {
  allowExtraFields?: boolean;
}

function createErrorResult(errors: string[]): ImportResult {
  return { success: false, errors };
}

function createSuccessResult(data: DatasetData): ImportResult {
  return { success: true, data };
}

function isValidDataObject(data: unknown): data is Record<string, unknown> {
  return Boolean(data) && typeof data === 'object' && !Array.isArray(data);
}

/** Formats an error with a prefix and extracted detail message. */
function formatError(prefix: string, error: unknown, fallback: string): string {
  const errDetail: string = error instanceof Error ? error.message : fallback;
  return `${prefix}${errDetail}`;
}

/** Attempts to parse a JSON string, returning data or an error message. */
function parseJsonSafe(
  jsonString: string,
  errorPrefix: string,
  fallback: string,
): { data: unknown } | { error: string } {
  try {
    return { data: JSON.parse(jsonString) };
  } catch (parseError) {
    return { error: formatError(errorPrefix, parseError, fallback) };
  }
}

/** Checks if a JSON string is syntactically valid. */
function isValidJson(jsonString: string): boolean {
  try {
    JSON.parse(jsonString);
    return true;
  } catch {
    return false;
  }
}

/** Extracts top-level field names from a JSON object string. */
function extractFieldNames(jsonString: string): string[] {
  try {
    const data = JSON.parse(jsonString);
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      return Object.keys(data);
    }
  } catch {
    // Ignore parse errors
  }
  return [];
}

/** Formats a list of validation errors into a single user-facing string. */
function formatValidationErrorList(errors: string[], multiplePrefix: string): string {
  if (errors.length === 0) {
    return '';
  }
  if (errors.length === 1) {
    return errors[0] ?? '';
  }
  return `${multiplePrefix}\n• ${errors.join('\n• ')}`;
}

/** Validates a JSON string, returning a typed ImportResult. */
function validateJson(
  jsonString: string,
  t: (key: string, opts?: Record<string, string>) => string,
): ImportResult {
  const fallback = t('errors.unknownError');
  const parseResult = parseJsonSafe(
    jsonString,
    t('errors.invalidJsonFormat', { error: '' }),
    fallback,
  );
  if ('error' in parseResult) {
    return createErrorResult([parseResult.error]);
  }
  const { data } = parseResult;
  if (!isValidDataObject(data)) {
    return createErrorResult([t('errors.dataMustBeObject')]);
  }
  return createSuccessResult(data as DatasetData);
}

interface UseJsonImportReturn {
  isValidating: boolean;
  lastValidation: ImportResult | null;
  validateJsonData: (jsonString: string, options?: ValidateJsonOptions) => ImportResult;
  importJsonData: (jsonString: string) => ImportResult;
  formatValidationErrors: (errors: string[]) => string;
  isValidJson: (jsonString: string) => boolean;
  extractFieldNames: (jsonString: string) => string[];
  clearValidation: () => void;
}

export function useJsonImport(): UseJsonImportReturn {
  const { t } = useTranslation('omakase.editor');
  const [isValidating, setIsValidating] = useState(false);
  const [lastValidation, setLastValidation] = useState<ImportResult | null>(null);

  const validateJsonData = (
    jsonString: string,
    _options: ValidateJsonOptions = {},
  ): ImportResult => {
    setIsValidating(true);
    try {
      return validateJson(jsonString, t);
    } catch (error) {
      return createErrorResult([
        formatError(t('errors.validationFailed', { error: '' }), error, t('errors.unknownError')),
      ]);
    } finally {
      setIsValidating(false);
    }
  };

  const importJsonData = (jsonString: string): ImportResult => {
    const result = validateJsonData(jsonString, { allowExtraFields: true });
    setLastValidation(result);
    return result;
  };

  return {
    isValidating,
    lastValidation,
    validateJsonData,
    importJsonData,
    formatValidationErrors: (errors: string[]) =>
      formatValidationErrorList(errors, t('errors.multipleValidationErrors')),
    isValidJson,
    extractFieldNames,
    clearValidation: () => setLastValidation(null),
  };
}
