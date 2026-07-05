/**
 * Hook to initialize all local stores from IndexedDB.
 * Called once at app startup. Returns initialization state so the root
 * component can gate rendering until stores are ready.
 *
 * Starts with isInitializing=true to prevent a flash-of-uninitialized-content.
 * The previous implementation started with isInitializing=false, which caused
 * the entire React tree (including forms) to mount, then unmount when the
 * effect kicked in, then remount after init completed. This destroyed any
 * React state (including form values) that was captured during the first mount.
 */

import { useEffect, useRef, useState } from 'react';
import { useDatasetStore } from '@/shared/model/local/datasetStore.ts';
import { useSchemaStore } from '@/shared/model/local/schemaStore.ts';
import { useTemplateStore } from '@/shared/model/local/templateStore.ts';

interface InitializationState {
  isInitializing: boolean;
  isInitialized: boolean;
  error: unknown | null;
}

export function useLocalStoreInit(): InitializationState {
  const [state, setState] = useState<InitializationState>({
    isInitializing: true,
    isInitialized: false,
    error: null,
  });

  const hasStarted = useRef(false);

  const templateInit = useTemplateStore((s) => s.initialize);
  const schemaInit = useSchemaStore((s) => s.initialize);
  const datasetInit = useDatasetStore((s) => s.initialize);

  const templateInitialized = useTemplateStore((s) => s.isInitialized);
  const schemaInitialized = useSchemaStore((s) => s.isInitialized);
  const datasetInitialized = useDatasetStore((s) => s.isInitialized);

  useEffect(() => {
    if (hasStarted.current) {
      return;
    }
    hasStarted.current = true;

    const initStores = async (): Promise<void> => {
      try {
        await Promise.all([templateInit(), schemaInit(), datasetInit()]);
        setState({ isInitializing: false, isInitialized: true, error: null });
      } catch (err) {
        setState({ isInitializing: false, isInitialized: false, error: err });
      }
    };

    initStores().catch(() => {
      // Error handled inside initStores via setState
    });
  }, [templateInit, schemaInit, datasetInit]);

  // Also detect if stores were initialized by another path (e.g., HMR)
  useEffect(() => {
    if (templateInitialized && schemaInitialized && datasetInitialized && !state.isInitialized) {
      setState({ isInitializing: false, isInitialized: true, error: null });
    }
  }, [templateInitialized, schemaInitialized, datasetInitialized, state.isInitialized]);

  return state;
}

/**
 * Hook that returns true only when all stores are ready.
 */
export function useStoresReady(): boolean {
  const templateReady = useTemplateStore((s) => s.isInitialized && !s.isLoading);
  const schemaReady = useSchemaStore((s) => s.isInitialized && !s.isLoading);
  const datasetReady = useDatasetStore((s) => s.isInitialized && !s.isLoading);

  return templateReady && schemaReady && datasetReady;
}
