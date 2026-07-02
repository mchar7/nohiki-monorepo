import { create, type UseBoundStore } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { StoreApi } from 'zustand/vanilla';
import { createDatasetSlice, type DatasetSlice, rebuildIndex } from './slices/datasetSlice.ts';
import {
  createTemplateRenderPrefsSlice,
  type TemplateRenderPrefsSlice,
} from './slices/templateRenderPrefsSlice.ts';
import {
  createVersionedTemplateSlice,
  type VersionedTemplateSlice,
} from './slices/versionedTemplateSlice.ts';

interface DocumentBuilderState
  extends VersionedTemplateSlice,
    DatasetSlice,
    TemplateRenderPrefsSlice {}

export const useDocumentBuilderStore: UseBoundStore<StoreApi<DocumentBuilderState>> =
  create<DocumentBuilderState>()(
    persist(
      (set, get, api) => ({
        ...createVersionedTemplateSlice(set, get, api),
        ...createDatasetSlice(
          set as Parameters<typeof createDatasetSlice>[0],
          get as Parameters<typeof createDatasetSlice>[1],
        ),
        ...createTemplateRenderPrefsSlice(set, get, api),
      }),
      {
        name: 'nohiki-document-builder-store',
        storage: createJSONStorage(() => localStorage),
        version: 1,
        partialize: (state: DocumentBuilderState) => ({
          templateFamilies: state.templateFamilies,
          selectedFamilyId: state.selectedFamilyId,
          selectedVersionId: state.selectedVersionId,
          datasets: state.datasets,
          activeDatasetId: state.activeDatasetId,
          templateRenderPrefs: state.templateRenderPrefs,
        }),
        onRehydrateStorage:
          (): ((state: DocumentBuilderState | undefined, error: unknown) => void) =>
          (state: DocumentBuilderState | undefined, error: unknown): void => {
            if (state && !error) {
              useDocumentBuilderStore.setState({
                datasetIndex: rebuildIndex(state.datasets),
              });
            }
          },
      },
    ),
  );

export function resetDocumentBuilderStore(): void {
  useDocumentBuilderStore.setState({
    templateFamilies: [],
    selectedFamilyId: null,
    selectedVersionId: null,
    currentTemplate: null,
    datasets: [],
    datasetIndex: new Map(),
    activeDatasetId: null,
    templateRenderPrefs: {},
  });
}
