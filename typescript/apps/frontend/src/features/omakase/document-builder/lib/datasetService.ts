import type { TemplateFamilyResponse } from '@/shared/api';
import type { Dataset, DatasetData } from '../model/index.ts';

const MAX_DATASET_NAME_LENGTH: number = 100;

/**
 * Validate dataset data structure
 */
export function validateDatasetStructure(data: unknown): data is DatasetData {
  return data !== null && typeof data === 'object' && !Array.isArray(data);
}

/**
 * Sanitize dataset data by ensuring proper structure
 */
export function sanitizeDatasetData(data: unknown): DatasetData {
  if (!validateDatasetStructure(data)) {
    return {};
  }

  // Create a clean copy removing any undefined values
  const sanitized: DatasetData = {};
  for (const [key, value] of Object.entries(data)) {
    if (value !== undefined) {
      sanitized[key] = value;
    }
  }

  return sanitized;
}

export function cloneDataset(
  dataset: Dataset,
  customName?: string,
): Omit<Dataset, 'id' | 'createdAt' | 'updatedAt'> {
  return {
    name: customName || `${dataset.name} (Copy)`,
    templateVersionId: dataset.templateVersionId,
    data: { ...dataset.data },
  };
}

export function findMostRecentDataset(datasets: Dataset[]): Dataset | null {
  if (datasets.length === 0) {
    return null;
  }

  const sorted = [...datasets].sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  );
  return sorted[0] ?? null;
}

export function getUniqueTemplates(
  datasets: Dataset[],
  templates: TemplateFamilyResponse[],
): TemplateFamilyResponse[] {
  const templatesById = new Map(templates.map((t) => [t.id, t]));
  const templateVersionIds = new Set(datasets.map((d) => d.templateVersionId));
  const result: TemplateFamilyResponse[] = [];
  for (const id of templateVersionIds) {
    const template = templatesById.get(id);
    if (template) {
      result.push(template);
    }
  }
  return result;
}

export function validateDatasetName(name: string): { isValid: boolean; error?: string } {
  if (!name.trim()) {
    return { isValid: false, error: 'Dataset name cannot be empty' };
  }

  if (name.length > MAX_DATASET_NAME_LENGTH) {
    return {
      isValid: false,
      error: `Dataset name must be ${MAX_DATASET_NAME_LENGTH} characters or less`,
    };
  }

  return { isValid: true };
}

export function generateUniqueDatasetName(baseName: string, existingDatasets: Dataset[]): string {
  const existingNames = new Set(existingDatasets.map((d) => d.name.toLowerCase()));

  if (!existingNames.has(baseName.toLowerCase())) {
    return baseName;
  }

  let counter = 1;
  let newName = `${baseName} (${counter})`;

  while (existingNames.has(newName.toLowerCase())) {
    counter += 1;
    newName = `${baseName} (${counter})`;
  }

  return newName;
}
