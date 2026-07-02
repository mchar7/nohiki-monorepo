import { useEffect, useState } from 'react';
import { createDevClient } from '@/shared/api';
import { normalizeEndpoint } from './useApiEndpointHealthCheck.ts';

const STORAGE_KEY = 'dev-api-endpoint';
const DEFAULT_ENDPOINT: string = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

interface ApiEndpointSettings {
  endpoint: string;
  setEndpoint: (endpoint: string) => void;
  isCustomEndpoint: boolean;
  resetToDefault: () => void;
  saveEndpoint: (endpoint: string) => void;
}

export function useApiEndpointSettings(): ApiEndpointSettings {
  const [endpoint, setEndpointState] = useState<string>(() => {
    // Only access localStorage in development mode
    if (!import.meta.env.DEV) {
      return DEFAULT_ENDPOINT;
    }

    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored || DEFAULT_ENDPOINT;
    } catch {
      return DEFAULT_ENDPOINT;
    }
  });

  const isCustomEndpoint = endpoint !== DEFAULT_ENDPOINT;

  // Recreate the dev client when the endpoint changes.
  // createDevClient returns a new isolated client instance for the omakase
  // editor - it does not affect the global fetchClient used by other features.
  useEffect(() => {
    createDevClient(endpoint);
  }, [endpoint]);

  const setEndpoint = (newEndpoint: string) => {
    setEndpointState(newEndpoint);

    // Only persist in development mode
    if (import.meta.env.DEV) {
      try {
        localStorage.setItem(STORAGE_KEY, newEndpoint);
      } catch {
        // Storage unavailable - endpoint only persists in memory
      }
    }
  };

  const resetToDefault = () => {
    setEndpointState(DEFAULT_ENDPOINT);

    // Only remove from localStorage in development mode
    if (import.meta.env.DEV) {
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch {
        // Storage unavailable - no cleanup needed
      }
    }
  };

  const saveEndpoint = (newEndpoint: string) => {
    // Normalize the endpoint before saving to handle trailing slashes and /api suffix
    const normalized = normalizeEndpoint(newEndpoint);
    setEndpoint(normalized);
  };

  return {
    endpoint,
    setEndpoint,
    isCustomEndpoint,
    resetToDefault,
    saveEndpoint,
  };
}
