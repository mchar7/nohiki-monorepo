import type { FieldErrors, UseFormRegister } from 'react-hook-form';

// --- Dataset ---

export type DatasetData = Record<string, unknown>;

export interface Dataset<TData extends DatasetData = DatasetData> {
  id: string;
  name: string;
  templateVersionId: string;
  data: TData;
  createdAt: string;
  updatedAt: string;
  cachedHtmlData?: string;
  htmlGeneratedAt?: string;
}

// --- Schema / Form ---

export type FormRegisterFunction = UseFormRegister<Record<string, unknown>>;

export type FormErrors = FieldErrors<Record<string, unknown>>;
