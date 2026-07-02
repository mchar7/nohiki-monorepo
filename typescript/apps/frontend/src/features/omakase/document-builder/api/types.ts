import type { ApiErrorType } from '@/shared/config/index.ts';

export interface ApiErrorDetails {
  error: ApiErrorType;
  message: string;
  details?: unknown;
}
