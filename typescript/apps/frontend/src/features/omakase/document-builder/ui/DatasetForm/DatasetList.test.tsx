import type { RenderResult } from '@testing-library/react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type React from 'react';
import { I18nextProvider } from 'react-i18next';
import { beforeEach, describe, expect, vi } from 'vitest';
import type { TemplateFamilyResponse } from '@/shared/api';
import { nonNull, wrapWithRouter } from '@/shared/test-utils';
import { i18n } from '@/test/setup.ts';
import type { Dataset, DatasetData } from '../../model/index.ts';
import { useDocumentBuilderStore } from '../../model/index.ts';
import { DatasetList } from './DatasetList.tsx';

const SEARCH_RE = /search/iu;
const NEW_DATASET_RE = /new dataset/iu;
const EXPORT_ALL_RE = /export all/iu;
const MORE_RE = /more/iu;
const DUPLICATE_RE = /duplicate/iu;
const DELETE_RE = /delete/iu;
const RENAME_RE = /rename/iu;
const DOWNLOAD_RE = /download/iu;

const mockNavigate = vi.fn().mockResolvedValue(undefined);
vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockCreateDataset = vi
  .fn<
    <TData extends DatasetData>(
      dataset: Omit<Dataset<TData>, 'id' | 'createdAt' | 'updatedAt'>,
    ) => string
  >()
  .mockReturnValue('new-dataset-id');
const mockUpdateDataset =
  vi.fn<<TData extends DatasetData>(id: string, updates: Partial<Dataset<TData>>) => void>();
const mockDeleteDataset = vi.fn<(id: string) => void>();
const mockSetActiveDataset = vi.fn<(id: string | null) => void>();

const mockTemplateFamily: TemplateFamilyResponse = {
  id: 'version-1',
  name: 'Resume Template',
  namespace: 'resume',
};

const mockDataset: Dataset = {
  id: 'dataset-1',
  name: 'My Resume',
  templateVersionId: 'version-1',
  data: { full_name: 'John Doe' },
  createdAt: '2024-01-01T00:00:00.000Z',
  updatedAt: '2024-01-02T00:00:00.000Z',
};

const mockDataset2: Dataset = {
  id: 'dataset-2',
  name: 'Cover Letter',
  templateVersionId: 'version-2',
  data: { content: 'Test content' },
  createdAt: '2024-01-03T00:00:00.000Z',
  updatedAt: '2024-01-04T00:00:00.000Z',
};

const mockDatasets: Dataset[] = [mockDataset, mockDataset2];
const mockDatasetIndex: Map<string, Dataset> = new Map(mockDatasets.map((d) => [d.id, d]));

async function renderDatasetList(
  props: Partial<React.ComponentProps<typeof DatasetList>> = {},
): Promise<RenderResult> {
  return render(
    await wrapWithRouter(
      <I18nextProvider i18n={i18n}>
        <DatasetList {...props} />
      </I18nextProvider>,
    ),
  );
}

/** Shared store setup applied before each test. */
function setupStore(): void {
  useDocumentBuilderStore.setState({
    datasets: mockDatasets,
    templateFamilies: [mockTemplateFamily],
    createDataset: mockCreateDataset,
    updateDataset: mockUpdateDataset,
    deleteDataset: mockDeleteDataset,
    setActiveDataset: mockSetActiveDataset,
    datasetIndex: mockDatasetIndex,
    getDataset: (id: string) => mockDatasetIndex.get(id),
  });
}

describe('DatasetList - rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStore();
  });

  test('renders datasets from the store', async () => {
    await renderDatasetList();
    expect(screen.getByText('My Resume')).toBeInTheDocument();
    expect(screen.getByText('Cover Letter')).toBeInTheDocument();
  });

  test('renders search input', async () => {
    await renderDatasetList();
    expect(screen.getByPlaceholderText(SEARCH_RE)).toBeInTheDocument();
  });

  test('renders create button when showCreateButton is true', async () => {
    await renderDatasetList({ showCreateButton: true });
    expect(screen.getByText(NEW_DATASET_RE)).toBeInTheDocument();
  });

  test('hides create button when showCreateButton is false', async () => {
    await renderDatasetList({ showCreateButton: false });
    expect(screen.queryByText(NEW_DATASET_RE)).not.toBeInTheDocument();
  });

  test('renders export all button when datasets exist', async () => {
    await renderDatasetList();
    expect(screen.getByText(EXPORT_ALL_RE)).toBeInTheDocument();
  });
});

describe('DatasetList - search', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStore();
  });

  test('allows typing in search input', async () => {
    const user = userEvent.setup();
    await renderDatasetList();

    const searchInput = screen.getByPlaceholderText(SEARCH_RE);
    await user.type(searchInput, 'Resume');

    await expect(searchInput).toHaveValue('Resume');
  });
});

describe('DatasetList - selection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStore();
  });

  test('calls onDatasetSelect when a dataset is selected', async () => {
    const onDatasetSelect = vi.fn();
    const user = userEvent.setup();
    await renderDatasetList({ onDatasetSelect });

    // Stream B changed div[role=button] to native <button>
    const card = screen.getByText('My Resume').closest('button');
    if (card) {
      await user.click(card);
    }

    expect(onDatasetSelect).toHaveBeenCalledWith(mockDataset);
  });

  test('highlights selected datasets', async () => {
    await renderDatasetList({ selectedDatasetIds: new Set(['dataset-1']) });

    const card = screen.getByText('My Resume').closest('button');
    await expect(card).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('DatasetList - create modal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStore();
  });

  test('opens create modal when new dataset button is clicked', async () => {
    const user = userEvent.setup();
    await renderDatasetList();

    await user.click(screen.getByText(NEW_DATASET_RE));

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
  });
});

describe('DatasetList - card duplicate and delete', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStore();
  });

  test('triggers duplicate via dropdown menu', async () => {
    const user = userEvent.setup();
    await renderDatasetList();

    const [menuButton] = screen.getAllByRole('button', { name: MORE_RE });
    await user.click(nonNull(menuButton));

    const duplicateItem = await screen.findByText(DUPLICATE_RE);
    await user.click(duplicateItem);

    expect(mockCreateDataset).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith({
      to: '/documents/editor/$datasetId',
      params: { datasetId: 'new-dataset-id' },
    });
  });

  test('triggers delete confirmation via dropdown menu', async () => {
    const user = userEvent.setup();
    await renderDatasetList();

    const [menuButton] = screen.getAllByRole('button', { name: MORE_RE });
    await user.click(nonNull(menuButton));

    const deleteItem = await screen.findByText(DELETE_RE);
    await user.click(deleteItem);

    await waitFor(() => {
      expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    });
  });
});

describe('DatasetList - card rename and download', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStore();
  });

  test('triggers rename via dropdown menu', async () => {
    const user = userEvent.setup();
    await renderDatasetList();

    const [menuButton] = screen.getAllByRole('button', { name: MORE_RE });
    await user.click(nonNull(menuButton));

    const renameItem = await screen.findByText(RENAME_RE);
    await user.click(renameItem);

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
  });

  test('triggers download via dropdown menu', async () => {
    const user = userEvent.setup();
    await renderDatasetList();

    const [menuButton] = screen.getAllByRole('button', { name: MORE_RE });
    await user.click(nonNull(menuButton));

    const downloadItem = await screen.findByText(DOWNLOAD_RE);
    await user.click(downloadItem);

    await waitFor(() => {
      expect(screen.getAllByRole('dialog').length).toBeGreaterThanOrEqual(1);
    });
  });
});
