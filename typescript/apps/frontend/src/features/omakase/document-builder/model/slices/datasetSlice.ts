import { nanoid } from 'nanoid';
import type { Dataset, DatasetData } from '../types.ts';

type SetState = (updater: (state: DatasetSlice) => Partial<DatasetSlice>) => void;
type GetState = () => DatasetSlice;

/** Rebuilds the dataset index from a list of datasets. */
function rebuildIndex(datasets: Dataset[]): Map<string, Dataset> {
  return new Map(datasets.map((d) => [d.id, d]));
}

/** Creates a new dataset, adds it to state, and returns its ID. */
function createDatasetAction<TData extends DatasetData>(
  set: SetState,
  dataset: Omit<Dataset<TData>, 'id' | 'createdAt' | 'updatedAt'>,
): string {
  const id = nanoid();
  const now = new Date().toISOString();
  const newDataset: Dataset = { ...dataset, id, createdAt: now, updatedAt: now };

  set((state: DatasetSlice) => {
    const newIndex = new Map(state.datasetIndex);
    newIndex.set(id, newDataset);
    return { datasets: [...state.datasets, newDataset], datasetIndex: newIndex };
  });

  return id;
}

/** Applies partial updates to a dataset by ID. */
function updateDatasetAction<TData extends DatasetData>(
  set: SetState,
  id: string,
  updates: Partial<Dataset<TData>>,
): void {
  set((state: DatasetSlice) => {
    const now = new Date().toISOString();
    const updatedDatasets = state.datasets.map((dataset) =>
      dataset.id === id ? { ...dataset, ...updates, updatedAt: now } : dataset,
    );
    return { datasets: updatedDatasets, datasetIndex: rebuildIndex(updatedDatasets) };
  });
}

/** Removes a dataset by ID, clearing activeDatasetId if it matches. */
function deleteDatasetAction(set: SetState, id: string): void {
  set((state: DatasetSlice) => {
    const newIndex = new Map(state.datasetIndex);
    newIndex.delete(id);
    return {
      datasets: state.datasets.filter((dataset) => dataset.id !== id),
      datasetIndex: newIndex,
      activeDatasetId: state.activeDatasetId === id ? null : state.activeDatasetId,
    };
  });
}

/** Sets cached HTML data and generation timestamp for a dataset. */
function setCachedHtmlAction(set: SetState, id: string, htmlData: string): void {
  set((state: DatasetSlice) => {
    const updatedDatasets = state.datasets.map((dataset) =>
      dataset.id === id
        ? { ...dataset, cachedHtmlData: htmlData, htmlGeneratedAt: new Date().toISOString() }
        : dataset,
    );
    return { datasets: updatedDatasets, datasetIndex: rebuildIndex(updatedDatasets) };
  });
}

/** Removes cached HTML data from a dataset. */
function clearCachedHtmlAction(set: SetState, id: string): void {
  set((state: DatasetSlice) => {
    const updatedDatasets = state.datasets.map((dataset) => {
      if (dataset.id !== id) {
        return dataset;
      }
      const { cachedHtmlData, htmlGeneratedAt, ...rest } = dataset;
      return rest as Dataset;
    });
    return { datasets: updatedDatasets, datasetIndex: rebuildIndex(updatedDatasets) };
  });
}

export interface DatasetSlice {
  datasets: Dataset[];
  datasetIndex: Map<string, Dataset>;
  activeDatasetId: string | null;

  createDataset: <TData extends DatasetData>(
    dataset: Omit<Dataset<TData>, 'id' | 'createdAt' | 'updatedAt'>,
  ) => string;
  updateDataset: <TData extends DatasetData>(id: string, updates: Partial<Dataset<TData>>) => void;
  deleteDataset: (id: string) => void;
  setActiveDataset: (id: string | null) => void;
  getDataset: (id: string) => Dataset | undefined;
  getDatasetsByTemplateVersion: (templateVersionId: string) => Dataset[];

  setCachedHtml: (id: string, htmlData: string) => void;
  clearCachedHtml: (id: string) => void;
}

export const createDatasetSlice = (set: SetState, get: GetState): DatasetSlice => ({
  datasets: [],
  datasetIndex: new Map(),
  activeDatasetId: null,

  createDataset: <TData extends DatasetData>(
    dataset: Omit<Dataset<TData>, 'id' | 'createdAt' | 'updatedAt'>,
  ): string => createDatasetAction(set, dataset),

  updateDataset: <TData extends DatasetData>(id: string, updates: Partial<Dataset<TData>>): void =>
    updateDatasetAction(set, id, updates),

  deleteDataset: (id: string): void => deleteDatasetAction(set, id),

  setActiveDataset: (id: string | null): void => {
    set((_state: DatasetSlice) => ({ activeDatasetId: id }));
  },

  getDataset: (id: string): Dataset | undefined => get().datasetIndex.get(id),

  getDatasetsByTemplateVersion: (templateVersionId: string): Dataset[] =>
    get().datasets.filter((dataset) => dataset.templateVersionId === templateVersionId),

  setCachedHtml: (id: string, htmlData: string): void => setCachedHtmlAction(set, id, htmlData),

  clearCachedHtml: (id: string): void => clearCachedHtmlAction(set, id),
});

export { rebuildIndex };
