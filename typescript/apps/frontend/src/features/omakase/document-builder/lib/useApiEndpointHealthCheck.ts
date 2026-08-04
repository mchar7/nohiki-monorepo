import type { TFunction } from 'i18next';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

const API_SUFFIX_LENGTH: number = 4;
const HEALTH_CHECK_TIMEOUT_MS: number = 10_000;

/**
 * Response from the API endpoint verification.
 * Uses template-families list response as a lightweight connectivity check.
 */
interface HealthResponse {
  status: string;
}

type HealthCheckState = 'idle' | 'checking' | 'success' | 'error';

interface HealthCheckResult {
  state: HealthCheckState;
  response?: HealthResponse;
  error?: string;
  latency?: number;
}

/**
 * Normalizes a user-provided API endpoint URL.
 * Handles common input variations:
 * - Trailing slashes: "http://localhost:8000/" → "http://localhost:8000"
 * - Accidental /api suffix: "http://localhost:8000/api" → "http://localhost:8000"
 * - Accidental /api/ suffix: "http://localhost:8000/api/" → "http://localhost:8000"
 * - Multiple trailing slashes: "http://localhost:8000///" → "http://localhost:8000"
 */
function normalizeEndpoint(url: string): string {
  let normalized = url.trim();

  // Remove trailing slashes
  while (normalized.endsWith('/')) {
    normalized = normalized.slice(0, -1);
  }

  // Remove accidental /api suffix (user shouldn't include this)
  if (normalized.endsWith('/api')) {
    normalized = normalized.slice(0, -API_SUFFIX_LENGTH);
  }

  return normalized;
}

/** Maps fetch errors to user-facing translated messages. */
function getErrorMessage(error: Error, t: TFunction<'settings'>): string {
  if (error.message.includes('CORS') || error.message.includes('Cross-Origin')) {
    return t('api.errors.corsError');
  }

  if (
    error.message.includes('Failed to fetch') ||
    error.message.includes('Network request failed')
  ) {
    return t('api.errors.networkError');
  }

  if (error.name === 'AbortError') {
    return t('api.errors.timeout');
  }

  return error.message;
}

/** Sends a ping request and returns the health check result (with translated errors). */
async function performHealthCheck(
  testEndpoint: string,
  t: TFunction<'settings'>,
): Promise<HealthCheckResult> {
  const startTime = Date.now();
  const normalizedEndpoint = normalizeEndpoint(testEndpoint);

  try {
    const response = await fetch(`${normalizedEndpoint}/api/ping`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      mode: 'cors',
      signal: AbortSignal.timeout(HEALTH_CHECK_TIMEOUT_MS),
    });

    const latency = Date.now() - startTime;

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data: HealthResponse = await response.json();
    return { state: 'success', response: data, latency };
  } catch (error) {
    const latency = Date.now() - startTime;
    const errorMessage: string =
      error instanceof Error ? getErrorMessage(error, t) : t('api.errors.unknownError');
    return { state: 'error', error: errorMessage, latency };
  }
}

function useApiEndpointHealthCheck(): {
  healthCheck: HealthCheckResult;
  validateUrl: (url: string) => boolean;
  testConnection: (inputValue: string) => Promise<boolean>;
  resetHealthCheck: () => void;
} {
  const { t } = useTranslation('settings');
  const [healthCheck, setHealthCheck] = useState<HealthCheckResult>({ state: 'idle' });

  const validateUrl = (url: string): boolean => {
    try {
      const normalized = normalizeEndpoint(url);
      const parsed = new URL(normalized);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch {
      return false;
    }
  };

  const testConnection = async (inputValue: string): Promise<boolean> => {
    if (!validateUrl(inputValue)) {
      setHealthCheck({ state: 'error', error: t('api.errors.invalidUrlFormat') });
      return false;
    }

    setHealthCheck({ state: 'checking' });
    const result = await performHealthCheck(inputValue, t);
    setHealthCheck(result);
    return result.state === 'success';
  };

  const resetHealthCheck = (): void => {
    setHealthCheck({ state: 'idle' });
  };

  return { healthCheck, validateUrl, testConnection, resetHealthCheck };
}

export type { HealthCheckResult, HealthResponse };
export { normalizeEndpoint, useApiEndpointHealthCheck };
