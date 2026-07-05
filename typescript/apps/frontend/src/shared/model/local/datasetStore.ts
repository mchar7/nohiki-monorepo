/**
 * Local dataset store with IndexedDB persistence.
 * Handles all local dataset CRUD operations.
 */

import { nanoid } from 'nanoid';
import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import { datasetPersistence } from '@/shared/lib/persistence/index.ts';
import type {
  CreateDatasetInput,
  DatasetMetadata,
  LocalDataset,
  UpdateDatasetInput,
} from '@/shared/model/dataset.types.ts';

interface DatasetState {
  datasets: LocalDataset[];
  datasetsById: Map<string, LocalDataset>;
  activeDatasetId: string | null;
  isLoading: boolean;
  isInitialized: boolean;
  error: string | null;
}

interface DatasetActions {
  initialize: () => Promise<void>;
  create: (input: CreateDatasetInput) => Promise<LocalDataset>;
  update: (id: string, input: UpdateDatasetInput) => Promise<LocalDataset | null>;
  delete: (id: string) => Promise<void>;
  clone: (id: string, newName?: string) => Promise<LocalDataset | null>;
  setActive: (id: string | null) => void;
  getById: (id: string) => LocalDataset | undefined;
  getByTemplateId: (templateId: string) => LocalDataset[];
  setCachedHtml: (id: string, html: string) => Promise<void>;
  clearCachedHtml: (id: string) => Promise<void>;
  importDatasets: (datasets: CreateDatasetInput[]) => Promise<LocalDataset[]>;
  clearAll: () => Promise<void>;
}

type DatasetStore = DatasetState & DatasetActions;
type SetFn = (
  partial: Partial<DatasetState> | ((state: DatasetState) => Partial<DatasetState>),
) => void;
type GetFn = () => DatasetStore;

const initialState: DatasetState = {
  datasets: [],
  datasetsById: new Map(),
  activeDatasetId: null,
  isLoading: false,
  isInitialized: false,
  error: null,
};

/** Build a new dataset record from user input. */
function buildDataset(input: CreateDatasetInput): LocalDataset {
  const now = new Date().toISOString();
  return {
    id: nanoid(),
    metadata: input.metadata,
    templateId: input.templateId,
    schemaId: null,
    data: input.data ?? {},
    createdAt: now,
    updatedAt: now,
    syncStatus: 'local-only',
  };
}

/** Merge update input into an existing dataset. */
function applyDatasetUpdate(existing: LocalDataset, input: UpdateDatasetInput): LocalDataset {
  return {
    ...existing,
    metadata: input.metadata ? { ...existing.metadata, ...input.metadata } : existing.metadata,
    data: input.data ?? existing.data,
    updatedAt: new Date().toISOString(),
    syncStatus: existing.remoteId ? 'pending-sync' : 'local-only',
    cachedHtml: input.data ? undefined : existing.cachedHtml,
    htmlCachedAt: input.data ? undefined : existing.htmlCachedAt,
  };
}

/** Immutably add a dataset to state. */
function addDatasetToState(
  state: DatasetState,
  dataset: LocalDataset,
): Pick<DatasetState, 'datasets' | 'datasetsById'> {
  const newDatasetsById = new Map(state.datasetsById);
  newDatasetsById.set(dataset.id, dataset);
  return { datasets: [...state.datasets, dataset], datasetsById: newDatasetsById };
}

/** Immutably replace a single dataset in the store state. */
function replaceDatasetInState(
  state: DatasetState,
  id: string,
  updated: LocalDataset,
): Pick<DatasetState, 'datasets' | 'datasetsById'> {
  const newDatasetsById = new Map(state.datasetsById);
  newDatasetsById.set(id, updated);
  return {
    datasets: state.datasets.map((d) => (d.id === id ? updated : d)),
    datasetsById: newDatasetsById,
  };
}

/** Remove a dataset from state. */
function removeDatasetFromState(
  state: DatasetState,
  id: string,
): Pick<DatasetState, 'datasets' | 'datasetsById' | 'activeDatasetId'> {
  const newDatasetsById = new Map(state.datasetsById);
  newDatasetsById.delete(id);
  return {
    datasets: state.datasets.filter((d) => d.id !== id),
    datasetsById: newDatasetsById,
    activeDatasetId: state.activeDatasetId === id ? null : state.activeDatasetId,
  };
}

/** Initialize from IndexedDB. */
async function handleInitialize(set: SetFn, get: GetFn): Promise<void> {
  if (get().isInitialized) {
    return;
  }
  set({ isLoading: true, error: null });
  try {
    const datasets = await datasetPersistence.getAll();
    const datasetsById = new Map(datasets.map((d) => [d.id, d]));
    set({ datasets, datasetsById, isLoading: false, isInitialized: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load datasets';
    set({ error: message, isLoading: false, isInitialized: true });
  }
}

/** Create and persist a new dataset. */
async function handleCreate(set: SetFn, input: CreateDatasetInput): Promise<LocalDataset> {
  const dataset = buildDataset(input);
  await datasetPersistence.set(dataset);
  set((state) => addDatasetToState(state, dataset));
  return dataset;
}

/** Persist and update a dataset's cached HTML. */
async function handleSetCachedHtml(
  set: SetFn,
  get: GetFn,
  id: string,
  html: string,
): Promise<void> {
  const existing = get().datasetsById.get(id);
  if (!existing) {
    return;
  }
  const updated: LocalDataset = {
    ...existing,
    cachedHtml: html,
    htmlCachedAt: new Date().toISOString(),
  };
  await datasetPersistence.set(updated);
  set((state) => replaceDatasetInState(state, id, updated));
}

/** Clear a dataset's cached HTML. */
async function handleClearCachedHtml(set: SetFn, get: GetFn, id: string): Promise<void> {
  const existing = get().datasetsById.get(id);
  if (!existing) {
    return;
  }
  const updated: LocalDataset = {
    ...existing,
    cachedHtml: undefined,
    htmlCachedAt: undefined,
  };
  await datasetPersistence.set(updated);
  set((state) => replaceDatasetInState(state, id, updated));
}

/** Clone a dataset with an optional new name. */
function handleClone(
  get: GetFn,
  id: string,
  newName?: string,
): Promise<LocalDataset | null> | null {
  const { datasetsById, create: createDataset } = get();
  const source = datasetsById.get(id);
  if (!source) {
    return null;
  }
  const clonedMetadata: DatasetMetadata = {
    ...source.metadata,
    name: newName ?? `${source.metadata.name} (Copy)`,
  };
  return createDataset({
    metadata: clonedMetadata,
    templateId: source.templateId,
    data: structuredClone(source.data),
  });
}

const useDatasetStore = create<DatasetStore>()(
  subscribeWithSelector((set, get) => ({
    ...initialState,
    initialize: () => handleInitialize(set, get),
    create: (input: CreateDatasetInput) => handleCreate(set, input),
    update: async (id: string, input: UpdateDatasetInput) => {
      const existing = get().datasetsById.get(id);
      if (!existing) {
        return null;
      }
      const updated = applyDatasetUpdate(existing, input);
      await datasetPersistence.set(updated);
      set((state) => replaceDatasetInState(state, id, updated));
      return updated;
    },
    delete: async (id: string) => {
      await datasetPersistence.delete(id);
      set((state) => removeDatasetFromState(state, id));
    },
    clone: (id: string, newName?: string) => Promise.resolve(handleClone(get, id, newName)),
    setActive: (id: string | null) => set({ activeDatasetId: id }),
    getById: (id: string) => get().datasetsById.get(id),
    getByTemplateId: (templateId: string) =>
      get().datasets.filter((d) => d.templateId === templateId),
    setCachedHtml: (id: string, html: string) => handleSetCachedHtml(set, get, id, html),
    clearCachedHtml: (id: string) => handleClearCachedHtml(set, get, id),
    importDatasets: (inputs: CreateDatasetInput[]) => {
      const { create: createDataset } = get();
      return Promise.all(inputs.map((input) => createDataset(input)));
    },
    clearAll: async () => {
      await datasetPersistence.clear();
      set({ datasets: [], datasetsById: new Map(), activeDatasetId: null });
    },
  })),
);

export { useDatasetStore };
